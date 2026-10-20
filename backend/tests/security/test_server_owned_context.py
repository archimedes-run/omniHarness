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
    "trigger_firing_id": "forged-firing",
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
    for key in ("agent_name", "turn_provenance", "trigger_rule_id", "trigger_firing_id", "called_agent"):
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
    TurnInjector(post=lambda path, body: sent.append(body) or {}, put=lambda *_: {}, get=lambda *_: {}).inject(tid, "rule-7", "do the thing", firing_id="firing-7")
    return sent[0]


@pytest.fixture
def engine_http(sec, monkeypatch):
    """The trigger engine's REAL gateway client (trigger_engine_wiring._gateway_call),
    with its httpx.Client pointed at this app instead of 127.0.0.1:8001."""
    from fastapi.testclient import TestClient

    from app.gateway import trigger_engine_wiring

    class _InApp(TestClient):
        def __init__(self, *args, **kwargs):
            super().__init__(sec.app)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("httpx.Client", _InApp)
    return trigger_engine_wiring


def test_synthetic_trigger_is_accepted_from_the_trigger_engine(sec, captured, engine_http) -> None:
    """End to end: TurnInjector over the engine's production HTTP call."""
    from app.trigger_engine.injector import TurnInjector

    post, put, get = engine_http._gateway_call("POST"), engine_http._gateway_call("PUT"), engine_http._gateway_call("GET")
    injector = TurnInjector(post=post, put=put, get=get)
    tid = injector.create_thread("rule-7")
    try:
        injector.inject(tid, "rule-7", "do the thing")
    except engine_http.GatewayCallFailed:
        pass  # the captured factory ends the run in error; the config is what matters
    [cfg] = captured
    assert cfg["context"]["turn_provenance"] == SYNTHETIC
    assert cfg["context"]["trigger_rule_id"] == "rule-7"
    # Feature 006: the firing id (the standing-grant cap's key) comes through
    # only with the trigger engine's grant.
    assert cfg["context"]["trigger_firing_id"] == "firing-7"
    from app.gateway.internal_auth import create_internal_auth_headers

    [record] = _runs(_internal_client(sec, create_internal_auth_headers()), tid)
    assert record["metadata"]["turn_provenance"] == SYNTHETIC


def _granted_post(sec, tid: str, payload: dict, nonce: str | None = None, *, issue_for: bytes | None = None, expect: tuple = (200, 500)):
    """Post exact bytes with the internal token and a grant (issued here unless given)."""
    import json as _json

    from app.gateway.internal_auth import TRIGGER_GRANT_HEADER_NAME, create_internal_auth_headers, issue_trigger_grant

    path = f"/api/threads/{tid}/runs/wait"
    content = _json.dumps(payload).encode()
    grant = nonce or issue_trigger_grant("POST", path, issue_for if issue_for is not None else content)
    client = _internal_client(sec, create_internal_auth_headers())
    resp = client.post(path, content=content, headers={"Content-Type": "application/json", TRIGGER_GRANT_HEADER_NAME: grant})
    assert resp.status_code in expect, resp.text
    return grant


def test_a_trigger_grant_is_single_use(sec, captured) -> None:
    from app.gateway.internal_auth import create_internal_auth_headers

    tid = _internal_client(sec, create_internal_auth_headers()).post("/api/threads", json={}).json()["thread_id"]
    payload = _trigger_payload(tid)
    grant = _granted_post(sec, tid, payload)
    _granted_post(sec, tid, payload, nonce=grant, expect=(403,))  # replay: refused outright
    [first] = captured  # the replay started no run at all
    assert first["context"].get("turn_provenance") == SYNTHETIC


def test_a_trigger_grant_is_bound_to_its_request(sec, captured) -> None:
    """A grant issued for one body does not mark a different body synthetic."""
    import json as _json

    from app.gateway.internal_auth import create_internal_auth_headers

    tid = _internal_client(sec, create_internal_auth_headers()).post("/api/threads", json={}).json()["thread_id"]
    payload = _trigger_payload(tid)
    other = dict(payload, input={"messages": [{"role": "human", "content": "something else"}]})
    _granted_post(sec, tid, other, issue_for=_json.dumps(payload).encode(), expect=(403,))
    assert captured == []  # refused, never downgraded to an ordinary turn


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
    assert "trigger_firing_id" not in cfg["context"]


def test_a_forged_trigger_grant_is_dropped(sec, captured) -> None:
    from app.gateway.internal_auth import create_internal_auth_headers

    tid = _internal_client(sec, create_internal_auth_headers()).post("/api/threads", json={}).json()["thread_id"]
    _granted_post(sec, tid, _trigger_payload(tid), nonce="A" * 43, expect=(403,))
    assert captured == []


def test_a_body_with_only_config_context_runs_on_the_authorised_thread(sec, monkeypatch) -> None:
    """Regression (#58 reviewer): config.context alone used to 500 with
    KeyError 'thread_id'. Now 200: the run gets the path's thread, and unknown
    context keys are dropped by the allowlist. A thread id in the body cannot
    redirect the run to another thread."""
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    seen: list[dict] = []

    def factory(config, **_):
        seen.append({"configurable": dict(config.get("configurable") or {}), "context": dict(config.get("context") or {})})
        return create_agent(model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])), tools=[])

    monkeypatch.setattr("app.gateway.services.resolve_agent_factory", lambda assistant_id: factory)
    owner = sec.owner
    tid = owner.post("/api/threads", json={}).json()["thread_id"]
    other = owner.post("/api/threads", json={}).json()["thread_id"]
    body = {"assistant_id": "lead_agent", "input": {"messages": [{"role": "human", "content": "hi"}]}, "config": {"context": {"foo": 1, "thinking_enabled": True}}}
    resp = owner.post(f"/api/threads/{tid}/runs/wait", json=body)
    assert resp.status_code == 200, resp.text
    assert seen[-1]["configurable"]["thread_id"] == tid
    assert "foo" not in seen[-1]["context"] and seen[-1]["context"].get("thinking_enabled") is True
    body = {"assistant_id": "lead_agent", "input": {"messages": [{"role": "human", "content": "hi"}]}, "config": {"configurable": {"thread_id": other}}}
    assert owner.post(f"/api/threads/{tid}/runs/wait", json=body).status_code == 200
    assert seen[-1]["configurable"]["thread_id"] == tid


def test_run_metadata_is_an_allowlist(sec, captured) -> None:
    owner = sec.owner
    tid = owner.post("/api/threads", json={}).json()["thread_id"]
    junk = {"title": "kept", "callbacks": [1], "__pregel_send": 1, "continue_action": "a1", "anything": "x"}
    body = {"assistant_id": "lead_agent", "input": {"messages": [{"role": "human", "content": "hi"}]}, "metadata": junk, "config": {"metadata": junk}}
    _run(owner, tid, body)
    [cfg] = captured
    assert cfg["metadata"].get("title") == "kept"
    for key in ("callbacks", "__pregel_send", "continue_action", "anything"):
        assert key not in cfg["metadata"], key
    [record] = _runs(owner, tid)
    assert set(record["metadata"]) <= {"title", "source"}, record["metadata"]
