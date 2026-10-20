"""Item 0b: run context keys only the server sets.

A client body that carries user_id / selected_sources / agent_name /
turn_provenance / trigger_rule_id / called_agent — in `context`,
`config.configurable`, `config.context` or `metadata` — is ignored. The
assertions read what the RUN ACTUALLY RECEIVES: the agent factory is replaced
by one that records the config `run_agent` hands it, after the worker has
installed the runtime context, and the run record is read back over HTTP.
Real HTTP, auth ON.
"""

from __future__ import annotations

import pytest

from app.policy.provenance import SYNTHETIC

FORGED = {
    "user_id": "someone-else",
    "selected_sources": ["mcp:forged-source"],
    "agent_name": "forged-agent",
    "turn_provenance": SYNTHETIC,
    "trigger_rule_id": "forged-rule",
    "called_agent": "forged-callee",
}
SERVER_OWNED = tuple(FORGED)


@pytest.fixture
def captured(monkeypatch):
    """Every config the agent factory is called with."""
    seen: list[dict] = []

    def factory(config, **_):
        seen.append({"configurable": dict(config.get("configurable") or {}), "context": dict(config.get("context") or {}), "metadata": dict(config.get("metadata") or {})})
        raise RuntimeError("captured; the test does not need a model")

    monkeypatch.setattr("app.gateway.services.resolve_agent_factory", lambda assistant_id: factory)
    return seen


def _forged_body(tid: str, **extra) -> dict:
    # body.context.agent_name is the chat UI's agent SELECTOR (see
    # test_the_agent_is_the_callers_choice_but_the_value_is_the_servers); every
    # other placement of every server-owned key is forged here.
    in_context = {k: v for k, v in FORGED.items() if k != "agent_name"}
    return {
        "assistant_id": "lead_agent",
        "input": {"messages": [{"role": "human", "content": "hello"}]},
        "context": in_context,
        "config": {"configurable": {"thread_id": tid, **FORGED}},
        "metadata": dict(FORGED),
        **extra,
    }


def _run(client, tid: str, body: dict) -> None:
    # The factory raises, so the run ends in error: 500 is expected here.
    resp = client.post(f"/api/threads/{tid}/runs/wait", json=body)
    assert resp.status_code in (200, 500), resp.text


def _runs(client, tid: str) -> list[dict]:
    resp = client.get(f"/api/threads/{tid}/runs")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_forged_body_is_ignored_and_the_server_values_reach_the_run(sec, captured) -> None:
    owner = sec.owner
    tid = owner.post("/api/threads", json={}).json()["thread_id"]
    stored = owner.put(f"/api/threads/{tid}/tools", json={"sources": []}).json()["sources"]

    _run(owner, tid, _forged_body(tid))

    [cfg] = captured
    ctx, configurable = cfg["context"], cfg["configurable"]
    # Set by the server, not taken from the body.
    assert ctx["user_id"] == sec.owner_id
    assert ctx["selected_sources"] == stored
    assert "mcp:forged-source" not in ctx["selected_sources"]
    # Absent: never from a request.
    for key in ("agent_name", "turn_provenance", "trigger_rule_id", "called_agent"):
        assert key not in ctx, key
        assert key not in configurable, key
    for key in SERVER_OWNED:
        assert key not in cfg["metadata"], key
    assert configurable.get("user_id") is None and configurable.get("selected_sources") is None

    # The run record (what injector.is_synthetic reads) carries no marker either.
    [record] = _runs(owner, tid)
    for key in SERVER_OWNED:
        assert key not in record["metadata"], key
    kwargs_cfg = record["kwargs"].get("config") or {}
    for section in ("configurable", "context", "metadata"):
        assert (kwargs_cfg.get(section) or {}).get("turn_provenance") is None, section


@pytest.mark.parametrize("selector", ["assistant_id", "context"])
def test_the_agent_is_the_callers_choice_but_the_value_is_the_servers(sec, captured, selector) -> None:
    """assistant_id (or the chat UI's body.context.agent_name) chooses which of
    the caller's own agents runs; the value the run gets is the server's
    normalised one, and a name hidden in config.* is not a choice."""
    owner = sec.owner
    tid = owner.post("/api/threads", json={}).json()["thread_id"]
    body = _forged_body(tid)
    if selector == "assistant_id":
        body["assistant_id"] = "My_Agent"
        body["context"]["agent_name"] = "ignored-when-assistant-id-names-one"
    else:
        body["context"]["agent_name"] = "My_Agent"
    _run(owner, tid, body)
    [cfg] = captured
    assert cfg["context"]["agent_name"] == "my-agent"
    assert cfg["configurable"]["agent_name"] == "my-agent"


def test_an_invalid_agent_choice_is_refused(sec, captured) -> None:
    owner = sec.owner
    tid = owner.post("/api/threads", json={}).json()["thread_id"]
    body = {"assistant_id": "lead_agent", "input": {"messages": []}, "context": {"agent_name": "../../etc"}}
    assert owner.post(f"/api/threads/{tid}/runs/wait", json=body).status_code == 422
    assert captured == []


# ── scheduled-run provenance ─────────────────────────────────────────────


def _internal_client(sec, headers: dict):
    from fastapi.testclient import TestClient

    client = TestClient(sec.app)
    client.cookies.set("csrf_token", "csrf-pair")
    client.headers.update({**headers, "X-CSRF-Token": "csrf-pair"})
    return client


def _trigger_payload(tid: str) -> dict:
    """Exactly what TurnInjector.inject posts."""
    from app.trigger_engine.injector import TurnInjector

    sent: list[dict] = []
    TurnInjector(post=lambda path, body: sent.append(body) or {}, put=lambda *_: {}, get=lambda *_: {}).inject(tid, "rule-7", "do the thing")
    return sent[0]


def test_synthetic_trigger_is_accepted_with_the_trigger_engines_credential(sec, captured) -> None:
    from app.gateway.internal_auth import create_trigger_engine_auth_headers

    engine = _internal_client(sec, create_trigger_engine_auth_headers())
    tid = engine.post("/api/threads", json={}).json()["thread_id"]
    _run(engine, tid, _trigger_payload(tid))
    [cfg] = captured
    assert cfg["context"]["turn_provenance"] == SYNTHETIC
    assert cfg["context"]["trigger_rule_id"] == "rule-7"
    [record] = _runs(engine, tid)
    assert record["metadata"]["turn_provenance"] == SYNTHETIC


def test_synthetic_trigger_is_dropped_for_the_internal_token_alone(sec, captured) -> None:
    """The channels (Telegram, Slack) hold the internal token. That is not the
    trigger engine's credential, so a channel message cannot be a scheduled run."""
    from app.gateway.internal_auth import create_internal_auth_headers

    channel = _internal_client(sec, create_internal_auth_headers())
    tid = channel.post("/api/threads", json={}).json()["thread_id"]
    _run(channel, tid, _trigger_payload(tid))
    [cfg] = captured
    assert "turn_provenance" not in cfg["context"]
    assert "turn_provenance" not in cfg["configurable"]
    [record] = _runs(channel, tid)
    assert "turn_provenance" not in record["metadata"]


def test_synthetic_trigger_is_dropped_for_the_owner(sec, captured) -> None:
    owner = sec.owner
    tid = owner.post("/api/threads", json={}).json()["thread_id"]
    _run(owner, tid, _trigger_payload(tid))
    [cfg] = captured
    assert "turn_provenance" not in cfg["context"]
    assert "trigger_rule_id" not in cfg["context"]


def test_a_forged_trigger_credential_is_dropped(sec, captured) -> None:
    from app.gateway.internal_auth import TRIGGER_ENGINE_HEADER_NAME, create_internal_auth_headers

    forged = _internal_client(sec, {**create_internal_auth_headers(), TRIGGER_ENGINE_HEADER_NAME: "0" * 64})
    tid = forged.post("/api/threads", json={}).json()["thread_id"]
    _run(forged, tid, _trigger_payload(tid))
    [cfg] = captured
    assert "turn_provenance" not in cfg["context"]
