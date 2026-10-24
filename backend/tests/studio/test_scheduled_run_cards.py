"""Cards and grants of SCHEDULED runs, in the production shape.

The gateway is `create_app()` with its real lifespan (the `studio` fixture:
auth on, the owner signed in); the trigger engine is `build_loop` calling this
app in-process with its own headers (see test_agent_schedules.py). Only the
model is scripted.

Two pre-existing faults, fixed here:

1. A Tier 3 card stated by a scheduled run (a lead automation, or a 006-F
   agent schedule) is on a thread the SYSTEM user owns (the engine creates
   it). Confirming it answered 404 "Thread not found" for the owner (decline
   worked). The install owner may now answer it; nobody else may, a scheduled
   turn still never answers anything, and it runs once.
2. The owner's Autonomy grants for the lead are stored under the owner's id,
   but a lead automation runs as the system user, so they never applied. A
   scheduled lead run now reads the OWNER's grants (only on the engine's
   granted request); Tier 3 still always waits, and no request can choose
   whose grants a run reads.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from test_agent_schedules import _cycle, _grant, _make_agent, _pending, _rules_file, _schedule, _task_call, script  # noqa: F401

MARS = AIMessage(content="", tool_calls=[{"name": "ledger_apply", "args": {"changes": [{"op": "create_project", "name": "Mars"}]}, "id": "p1"}])


def _engine(studio, *, tamper=None):
    """build_loop calling this app in-process (test_agent_schedules._engine),
    with an optional `tamper(body)` applied to a run's body BEFORE it is signed:
    what the engine sends, byte for byte, is what the grant is bound to."""
    from app.gateway.trigger_engine_wiring import GatewayCallFailed, build_loop, engine_request_headers, owner_agent_exists

    client = studio.client
    calls: list = []

    def verb(method: str):
        def call(path: str, body: dict | None = None) -> dict:
            if tamper is not None and body is not None and path.endswith("/runs/wait"):
                tamper(body)
            calls.append((method, path, body))
            content = json.dumps(body).encode() if body is not None else b""
            resp = client.request(method, path, content=content or None, headers=engine_request_headers(method, path, content))
            if resp.is_error:
                raise GatewayCallFailed(method, path, resp)
            return resp.json() if resp.content else {}

        return call

    loop = build_loop(
        client.app.state.config,
        gateway_post=verb("POST"),
        gateway_put=verb("PUT"),
        gateway_get=verb("GET"),
        fetch_sessions=lambda: {"observable": True, "sessions": []},
        exchange_state=lambda tid: {"status": "idle"},
        remote=None,
        agent_exists=owner_agent_exists(lambda coro: client.portal.call(lambda: coro)),
    )
    return SimpleNamespace(loop=loop, calls=calls, runs=lambda: [c for c in calls if c[1].endswith("/runs/wait")])


def _projects(client) -> list[str]:
    return [p["name"] for p in client.get("/api/ledger/projects").json()]


def _system_projects() -> list[str]:
    from omniharness.runtime.ledger.controller import get_ledger_controller
    from omniharness.runtime.user_context import DEFAULT_USER_ID

    return [p["name"] for p in get_ledger_controller().service.repo.projects(DEFAULT_USER_ID)]


def _ran(studio, agent: str = "lead_agent") -> int:
    """How many "Mars" projects exist, in the owner's ledger AND the system's:
    a lead automation runs as the system user, so its confirmed call acts in
    the system's ledger (pre-existing, see the report); a 006-F agent schedule
    runs for the owner, so in the owner's. Counted in both, it ran once or not."""
    return _system_projects().count("Mars") + _projects(studio.client).count("Mars")


def _second_account(studio, monkeypatch):
    """A second account, ADMITTED (the door opened), so a refusal below is the
    confirmation route's own check and not the sign-in refusal."""
    from fastapi.testclient import TestClient

    from app.gateway.deps import get_local_provider

    async def create():
        return await get_local_provider().create_user(email="second@example.com", password="An0ther!Pass77", system_role="user")

    user = studio.client.portal.call(create)
    monkeypatch.setattr("app.gateway.ownership.admits_additional_accounts", lambda: True)
    other = TestClient(studio.client.app)
    assert other.post("/api/v1/auth/login/local", data={"username": "second@example.com", "password": "An0ther!Pass77"}).status_code == 200
    if other.cookies.get("csrf_token"):
        other.headers["X-CSRF-Token"] = other.cookies.get("csrf_token")
    assert other.get("/api/agents").status_code == 200, "not admitted: a refusal would pass for the wrong reason"
    return SimpleNamespace(client=other, user_id=str(user.id))


def _scheduled_card(studio, script, *, agent: str = "lead_agent"):  # noqa: F811
    """A scheduled run of `agent` states a Tier 3 plan (a new project)."""
    _rules_file(studio)
    if agent != "lead_agent":
        _make_agent(studio, agent)
    engine = _engine(studio)
    written = _schedule(studio, agent=agent)
    script.steps.append(MARS)
    _cycle(engine)
    [plan] = _pending(studio)
    [(_, path, _)] = engine.runs()
    tid = path.split("/")[3]
    assert plan["thread_id"] == tid
    # The precondition this file is about: the run's thread is the SYSTEM's.
    from omniharness.runtime.user_context import DEFAULT_USER_ID

    row = studio.client.portal.call(lambda: studio.client.app.state.thread_store.get(tid, user_id=None))
    assert row is not None and row["user_id"] == DEFAULT_USER_ID, row
    return SimpleNamespace(plan=plan, tid=tid, engine=engine, rule_id=written["rule_id"])


# -- BUG 1: the owner can answer a scheduled run's card ------------------------


@pytest.mark.parametrize("agent", ["lead_agent", "wrap-up"])
def test_the_owner_confirms_a_scheduled_runs_card_and_it_runs_once(studio, script, agent) -> None:  # noqa: F811
    card = _scheduled_card(studio, script, agent=agent)
    assert _ran(studio, agent) == 0

    resp = studio.client.post(f"/api/confirmations/{card.plan['id']}/confirm", json={})

    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "executed", resp.json()
    assert _ran(studio, agent) == 1
    again = studio.client.post(f"/api/confirmations/{card.plan['id']}/confirm", json={})
    assert again.status_code == 200 and again.json()["outcome"] != "executed", again.text
    assert _ran(studio, agent) == 1, "a second confirmation ran it again"
    assert _pending(studio) == []


def test_two_confirmations_at_once_run_a_scheduled_card_once(studio, script) -> None:  # noqa: F811
    card = _scheduled_card(studio, script)
    url = f"/api/confirmations/{card.plan['id']}/confirm"

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: studio.client.post(url, json={}), range(2)))

    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    outcomes = sorted(r.json()["outcome"] for r in responses)
    assert outcomes.count("executed") == 1, outcomes
    assert _ran(studio) == 1


def test_the_owner_can_still_decline_a_scheduled_runs_card(studio, script) -> None:  # noqa: F811
    card = _scheduled_card(studio, script)
    resp = studio.client.post(f"/api/confirmations/{card.plan['id']}/decline", json={})
    assert resp.status_code == 200 and resp.json()["outcome"] == "declined", resp.text
    assert _ran(studio) == 0


@pytest.mark.parametrize("agent", ["lead_agent", "wrap-up"])
def test_another_account_cannot_confirm_decline_or_edit_a_scheduled_runs_card(studio, script, monkeypatch, agent) -> None:  # noqa: F811
    card = _scheduled_card(studio, script, agent=agent)
    other = _second_account(studio, monkeypatch)
    pid = card.plan["id"]

    assert other.client.post(f"/api/confirmations/{pid}/confirm", json={}).status_code in (403, 404)
    assert other.client.post(f"/api/confirmations/{pid}/decline", json={}).status_code in (403, 404)
    assert other.client.post(f"/api/confirmations/{pid}/edit", json={"arguments": {"changes": [{"op": "create_project", "name": "Mars"}]}}).status_code in (403, 404)
    assert [a["id"] for a in _pending(studio)] == [pid], "another account resolved the owner's card"
    assert _ran(studio, agent) == 0 and "Mars" not in _projects(other.client)

    # The control: the same card IS answerable, by the owner.
    resp = studio.client.post(f"/api/confirmations/{pid}/confirm", json={})
    assert resp.status_code == 200 and resp.json()["outcome"] == "executed", resp.text


def test_the_internal_principal_cannot_confirm_a_scheduled_runs_card(studio, script) -> None:  # noqa: F811
    """The engine's own credential (what a scheduled run's process holds) is
    never the person pressing the button."""
    from app.gateway.trigger_engine_wiring import engine_request_headers

    card = _scheduled_card(studio, script)
    path = f"/api/confirmations/{card.plan['id']}/confirm"
    resp = studio.client.post(path, content=b"{}", headers=engine_request_headers("POST", path, b"{}"))
    assert resp.status_code == 403, resp.text
    assert _ran(studio) == 0
    assert studio.client.post(path, json={}).json()["outcome"] == "executed"


def test_a_scheduled_lead_runs_own_yes_never_confirms_its_card(studio, script) -> None:  # noqa: F811
    card = _scheduled_card(studio, script)

    card.engine.loop.runner.injector.inject(card.tid, card.rule_id, f"yes {card.plan['id']}", firing_id="fire-yes")
    card.engine.loop.runner.injector.inject(card.tid, card.rule_id, "yes", firing_id="fire-yes-2")

    assert [a["id"] for a in _pending(studio)] == [card.plan["id"]], "a scheduled turn answered a card"
    assert _ran(studio) == 0
    # The control: the card is still the owner's to confirm.
    resp = studio.client.post(f"/api/confirmations/{card.plan['id']}/confirm", json={})
    assert resp.status_code == 200 and resp.json()["outcome"] == "executed", resp.text


def test_a_card_on_a_thread_another_account_owns_stays_refused_to_the_owner(studio, script, monkeypatch) -> None:  # noqa: F811
    """The owner gains threads the SYSTEM owns, not another person's: a card
    whose thread belongs to a second account is still 404 to the owner."""
    card = _scheduled_card(studio, script)
    other = _second_account(studio, monkeypatch)
    from sqlalchemy import update

    from omniharness.persistence.engine import get_session_factory
    from omniharness.persistence.thread_meta.model import ThreadMetaRow

    async def give_away():
        async with get_session_factory()() as session:
            await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == card.tid).values(user_id=other.user_id))
            await session.commit()

    studio.client.portal.call(give_away)
    resp = studio.client.post(f"/api/confirmations/{card.plan['id']}/confirm", json={})
    assert resp.status_code == 404, resp.text
    assert _ran(studio) == 0


def test_only_the_install_owner_gains_a_system_threads_card(studio, script, monkeypatch) -> None:  # noqa: F811
    """A card on a system-owned thread whose RECORD names a second account (a
    record edited on disk): the record check lets that account through, the
    thread rule does not. Owning the card is not enough; only the install
    owner answers on the system's threads."""
    from dataclasses import replace

    from app.policy.registration import build
    from omniharness.config import get_app_config

    card = _scheduled_card(studio, script)
    other = _second_account(studio, monkeypatch)
    store = build(get_app_config()).pending
    store.save(replace(store.get(card.plan["id"]), owner_id=other.user_id))

    resp = other.client.post(f"/api/confirmations/{card.plan['id']}/confirm", json={})

    assert resp.status_code == 404, resp.text
    assert _ran(studio) == 0 and "Mars" not in _projects(other.client)


def test_a_waiting_result_of_an_agent_schedules_card_is_posted_at_startup(studio, script) -> None:  # noqa: F811
    """The card's owner is the owner (006-F runs the agent for them) while its
    thread is the system's: the startup drain posts it, as it does any other."""
    from app.gateway.routers.confirmations import drain_waiting_posts
    from app.policy.registration import build
    from omniharness.config import get_app_config

    card = _scheduled_card(studio, script, agent="wrap-up")
    assert card.plan["owner_id"] == studio.user_id
    store = build(get_app_config()).pending
    # Confirmed and recorded "waiting to post", as a gateway that stopped
    # between the run and the post leaves it.
    from app.policy.confirm_flow import take_claim
    from app.policy.models import Outcome

    claimed = take_claim(store, card.plan["id"], "test")
    store.resolve(claimed, Outcome.EXECUTED, "done")
    store.set_post_state(card.plan["id"], "waiting")
    assert [a.id for a in store.awaiting_post()] == [card.plan["id"]]

    posted = studio.client.portal.call(drain_waiting_posts, studio.client.app)

    assert posted == 1


# -- BUG 2: the owner's lead grants reach a scheduled lead run ----------------


def _system_ledger_project(name: str = "Launch") -> None:
    """Where a lead automation's ledger calls land: the run's user is the
    system user (pre-existing; see the report). Seeded so a granted write
    succeeds; whether it RUNS is what these tests are about."""
    from omniharness.runtime.ledger.controller import get_ledger_controller
    from omniharness.runtime.user_context import DEFAULT_USER_ID

    get_ledger_controller().service.apply(user_id=DEFAULT_USER_ID, changes=[{"op": "create_project", "name": name}], thread_id=None, actor="user")


def _system_tasks() -> list[str]:
    from omniharness.runtime.ledger.controller import get_ledger_controller
    from omniharness.runtime.user_context import DEFAULT_USER_ID

    return [line for line in get_ledger_controller().read(user_id=DEFAULT_USER_ID, project="Launch").splitlines() if "Draft" in line or "Wire" in line]


def test_the_owners_lead_grant_applies_to_a_scheduled_lead_run(studio, script) -> None:  # noqa: F811
    _rules_file(studio)
    _system_ledger_project()
    _grant(studio, "lead_agent", ["tasks"])
    engine = _engine(studio)
    written = _schedule(studio, agent="lead_agent")
    script.steps.append(_task_call("Draft the release notes"))

    _cycle(engine)

    assert _pending(studio) == [], "the owner's lead grant did not reach the scheduled lead run"
    assert any("Draft the release notes" in t for t in _system_tasks())
    [use] = studio.client.get("/api/studio/agents/lead_agent/grant-uses").json()
    assert (use["rule_id"], use["classes"]) == (written["rule_id"], ["tasks"])


def test_without_the_owners_grant_a_scheduled_lead_run_waits(studio, script) -> None:  # noqa: F811
    """The control for the test above: same run, no grant, it waits."""
    _rules_file(studio)
    _system_ledger_project()
    engine = _engine(studio)
    _schedule(studio, agent="lead_agent")
    script.steps.append(_task_call("Draft the release notes"))
    _cycle(engine)
    assert len(_pending(studio)) == 1 and _system_tasks() == []


def test_tier_3_still_waits_in_a_scheduled_lead_run_with_every_grant(studio, script) -> None:  # noqa: F811
    _rules_file(studio)
    _system_ledger_project()
    _grant(studio, "lead_agent", ["tasks", "notes", "archive"])
    engine = _engine(studio)
    _schedule(studio, agent="lead_agent")
    script.steps += [MARS, _task_call("Draft the release notes", "c2")]

    _cycle(engine)

    # The control: the grant is live in this run (the routine write ran)...
    assert any("Draft the release notes" in t for t in _system_tasks()), "the grant did not apply: the Tier 3 check below would pass for the wrong reason"
    # ...and the new project still waits for the person.
    [waiting] = _pending(studio)
    assert waiting["arguments"]["changes"][0]["op"] == "create_project"
    assert _ran(studio) == 0


GRANTS_KEY = "grants_owner_id"


def test_a_scheduled_run_cannot_choose_whose_grants_it_reads(studio, script, monkeypatch) -> None:  # noqa: F811
    """A second account holds a lead grant; the owner holds none. A scheduled
    lead run whose (engine-signed) body names the second account as the grants'
    owner, in every container a run body has, still reads the OWNER's: it waits."""
    _rules_file(studio)
    _system_ledger_project()
    other = _second_account(studio, monkeypatch)
    version = other.client.get("/api/studio/agents/lead_agent/autonomy").json()["version"]
    assert other.client.put("/api/studio/agents/lead_agent/autonomy", json={"granted": ["tasks"], "base_version": version}).status_code == 200

    def forge(body: dict) -> None:
        body["config"]["configurable"][GRANTS_KEY] = other.user_id
        body["config"].setdefault("metadata", {})[GRANTS_KEY] = other.user_id
        body["metadata"][GRANTS_KEY] = other.user_id
        body["context"] = {GRANTS_KEY: other.user_id}

    engine = _engine(studio, tamper=forge)
    _schedule(studio, agent="lead_agent")
    script.steps.append(_task_call("Wire the money"))

    _cycle(engine)

    assert engine.runs(), "no run happened"
    assert _system_tasks() == [], "a run body chose whose grants the run read"
    assert len(_pending(studio)) == 1


def test_a_client_supplied_grants_owner_is_dropped_from_every_container() -> None:
    """The server-owned key, whatever a request puts where."""
    from app.gateway.services import SERVER_OWNED_RUN_KEYS, apply_server_owned_context

    assert GRANTS_KEY in SERVER_OWNED_RUN_KEYS
    config = {"configurable": {GRANTS_KEY: "x"}, "context": {GRANTS_KEY: "x"}, "metadata": {GRANTS_KEY: "x"}}
    metadata = {GRANTS_KEY: "x"}
    apply_server_owned_context(config, metadata, user_id="u", selected_sources=None, agent_name=None, synthetic_rule_id=None, synthetic_firing_id=None)
    assert GRANTS_KEY not in config["configurable"] and GRANTS_KEY not in config["context"]
    assert GRANTS_KEY not in config["metadata"] and GRANTS_KEY not in metadata
