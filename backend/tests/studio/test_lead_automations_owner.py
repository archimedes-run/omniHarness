"""#133: a lead automation runs for the install owner, in the production shape.

The gateway is `create_app()` with its real lifespan (auth on, the owner
signed in); the trigger engine is `build_loop` calling this app in-process
with its own headers (test_agent_schedules._engine). Only the model is
scripted. Before the fix a scheduled run of the LEAD ran as the system user:
its granted writes and confirmed calls landed in the system's ledger (the
owner never saw them, and Undo on the run could not find them) and its files
under the system's directory. A 006-F agent schedule already ran for the
owner; the lead now does the same.

Unchanged, and checked here: the thread stays the system's (the card rule,
#132), a second account cannot reach it or its cards.

The startup migration moves an existing automation thread's files from the
system user to the owner (app.run_history.owner_migration): through a real
restart of the gateway here, and its safety (idempotent, never overwrites,
partial failure) on temporary directories in test_owner_migration.py.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from test_agent_schedules import _cycle, _grant, _pending, _rules_file, _schedule, _task_call, script  # noqa: F401
from test_scheduled_run_cards import MARS, _engine, _projects, _second_account, _system_projects

SECRET = "REPORT-MARKER-7f3c: last week's numbers"


def _owner_task_titles(studio) -> list[str]:
    [project] = [p for p in studio.client.get("/api/ledger/projects").json() if p["name"] == "Launch"]
    return [t["title"] for t in studio.client.get(f"/api/ledger/projects/{project['id']}").json()["tasks"]]


def _write_report(text: str = SECRET) -> AIMessage:
    """The run saves a report into its thread's outputs (the file tools act
    in the run user's directory for the thread)."""
    return AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"description": "save the report", "path": "/mnt/user-data/outputs/report.md", "content": text}, "id": "w1"}])


def _thread_of(engine) -> str:
    [(_, path, _)] = engine.runs()
    return path.split("/")[3]


def _dirs(studio, tid: str):
    from omniharness.config.paths import get_paths
    from omniharness.runtime.user_context import DEFAULT_USER_ID

    paths = get_paths()
    return paths.thread_dir(tid, user_id=studio.user_id), paths.thread_dir(tid, user_id=DEFAULT_USER_ID)


# -- the run is the owner's ----------------------------------------------------


def test_a_lead_automations_granted_write_is_the_owners_and_undo_finds_it(studio, script) -> None:  # noqa: F811
    _rules_file(studio)
    assert studio.client.post("/api/ledger/projects", json={"name": "Launch"}).status_code == 201
    _grant(studio, "lead_agent", ["tasks"])
    engine = _engine(studio)
    _schedule(studio, agent="lead_agent")
    script.steps.append(_task_call("Draft the release notes"))

    _cycle(engine)

    assert _pending(studio) == [], "the grant did not apply: nothing below would be tested"
    assert _owner_task_titles(studio) == ["Draft the release notes"], "the granted write is not in the owner's ledger"
    assert _system_projects() == [], "the lead automation wrote into the system user's ledger"
    [use] = studio.client.get("/api/studio/agents/lead_agent/grant-uses").json()
    summary = studio.client.get(f"/api/studio/runs/{use['firing_id']}")
    assert summary.status_code == 200, summary.text
    [write] = summary.json()["writes"]
    assert write["undoable"] and not write["undone"]

    undone = studio.client.post(f"/api/studio/runs/{use['firing_id']}/undo")

    assert undone.status_code == 200, undone.text
    assert undone.json()["all_undone"] is True
    assert _owner_task_titles(studio) == [], "Undo on the run did not revert the owner's write"


def test_a_lead_automations_confirmed_card_acts_in_the_owners_ledger(studio, script) -> None:  # noqa: F811
    _rules_file(studio)
    engine = _engine(studio)
    _schedule(studio, agent="lead_agent")
    script.steps.append(MARS)
    _cycle(engine)
    [plan] = _pending(studio)
    assert plan["owner_id"] == studio.user_id, "the card is not the owner's"

    resp = studio.client.post(f"/api/confirmations/{plan['id']}/confirm", json={})

    assert resp.status_code == 200 and resp.json()["outcome"] == "executed", resp.text
    assert _projects(studio.client) == ["Mars"], "the confirmed call did not act in the owner's ledger"
    assert "Mars" not in _system_projects(), "the confirmed call acted in the system user's ledger"


def test_a_lead_automations_files_are_under_the_owner_and_its_thread_stays_the_systems(studio, script, monkeypatch) -> None:  # noqa: F811
    from omniharness.runtime.user_context import DEFAULT_USER_ID

    _rules_file(studio)
    engine = _engine(studio)
    _schedule(studio, agent="lead_agent")
    script.steps.append(_write_report())
    _cycle(engine)
    tid = _thread_of(engine)

    owner_dir, system_dir = _dirs(studio, tid)
    assert (owner_dir / "user-data" / "outputs" / "report.md").read_text() == SECRET, "the run's file is not under the owner"
    assert not system_dir.exists(), "the run still wrote under the system user"
    # Unchanged: the engine's thread is the system's, so the card rule (#132)
    # holds and a second account reaches neither the thread nor its cards.
    row = studio.client.portal.call(lambda: studio.client.app.state.thread_store.get(tid, user_id=None))
    assert row["user_id"] == DEFAULT_USER_ID
    other = _second_account(studio, monkeypatch)
    assert other.client.get(f"/api/threads/{tid}/state").status_code in (403, 404)
    assert other.client.get(f"/api/threads/{tid}").status_code in (403, 404)


def test_without_an_owner_a_lead_automation_still_runs_as_the_caller(monkeypatch) -> None:
    """No accounts (auth off): nobody to run for; it runs as before."""
    from app.gateway import services

    async def no_owner():
        return None

    monkeypatch.setattr("app.gateway.ownership.owner_user_id", no_owner)
    assert asyncio.run(services._scheduled_lead_owner("default")) == ("default", None)


def test_deleting_the_run_history_deletes_the_owners_copy_of_the_files(studio, script) -> None:  # noqa: F811
    """'Delete run history' deletes the automations' threads, files included;
    their files are now under the owner, and are deleted there."""
    _rules_file(studio)
    engine = _engine(studio, note=True)
    _schedule(studio, agent="lead_agent")
    script.steps.append(_write_report())
    _cycle(engine)
    tid = _thread_of(engine)
    owner_dir, _ = _dirs(studio, tid)
    assert (owner_dir / "user-data" / "outputs" / "report.md").exists()

    resp = studio.client.delete("/api/run-history/runs", params={"confirm": "delete-all"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["threads_deleted"] == 1, resp.json()
    assert not owner_dir.exists(), "the automation thread's files were left under the owner"


# -- the startup migration, through a real restart -----------------------------


def _engine_noting(studio):
    """`_engine`, with the run history told of each thread the engine creates
    (production passes `note_thread`; the shared helper does not)."""
    return _engine(studio, note=True)


@pytest.fixture
def restartable(tmp_path, monkeypatch):
    """The `studio` gateway, but started by the test, as many times as it
    likes, on the same data: `start()` returns a signed-in client in a
    running app (close it before starting again)."""
    from studio_app import configure_studio, fresh_app

    import app.gateway.deps as deps
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    configure_studio(tmp_path, monkeypatch)
    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(deps, "_cached_repo", None)
    state = SimpleNamespace(first=True)

    def start() -> TestClient:
        client = TestClient(fresh_app())
        client.__enter__()
        if state.first:
            resp = client.post("/api/v1/auth/initialize", json={"email": "owner@example.com", "password": "Str0ng!Pass99"})
            state.first = False
        else:
            resp = client.post("/api/v1/auth/login/local", data={"username": "owner@example.com", "password": "Str0ng!Pass99"})
        assert resp.status_code in (200, 201), resp.text
        if client.cookies.get("csrf_token"):
            client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
        return client

    yield SimpleNamespace(start=start, tmp=tmp_path)
    reset_app_config()
    reset_extensions_config()


def _studio_of(client, tmp) -> SimpleNamespace:
    me = client.get("/api/v1/auth/me").json()
    return SimpleNamespace(client=client, user_id=str(me.get("id") or me.get("user", {}).get("id")), tmp=tmp)


def _read_report(tid: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"description": "last report", "path": "/mnt/user-data/outputs/report.md"}, "id": f"r-{tid[:6]}"}])


def _tool_results(studio, tid: str) -> list[str]:
    from app.gateway.trigger_engine_wiring import engine_request_headers

    path = f"/api/threads/{tid}/state"
    resp = studio.client.get(path, headers=engine_request_headers("GET", path, b""))
    assert resp.status_code == 200, resp.text
    return [str(m.get("content")) for m in resp.json()["values"]["messages"] if m.get("type") == "tool"]


def _old_layout_thread(restartable, script) -> SimpleNamespace:  # noqa: F811
    """An automation thread as an older version left it: its files under the
    SYSTEM user. Made from a real firing (the engine creates the thread, the
    run history notes it, the rule maps to it) whose directory is then moved
    to where the old code put it. The gateway is stopped on return."""
    import shutil

    client = restartable.start()
    try:
        studio = _studio_of(client, restartable.tmp)
        _rules_file(studio)
        engine = _engine_noting(studio)
        rule_id = _schedule(studio, agent="lead_agent")["rule_id"]
        script.steps.append(_write_report())
        _cycle(engine)
        tid = _thread_of(engine)
        owner_dir, system_dir = _dirs(studio, tid)
        system_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(owner_dir), str(system_dir))
        assert (system_dir / "user-data" / "outputs" / "report.md").read_text() == SECRET
    finally:
        client.__exit__(None, None, None)
    return SimpleNamespace(tid=tid, rule_id=rule_id, owner_dir=owner_dir, system_dir=system_dir)


def test_after_a_restart_an_existing_lead_automation_keeps_its_files(restartable, script) -> None:  # noqa: F811
    """The gateway restarts on an old-layout automation thread; the startup
    migration moves its files to the owner, and the automation's next firing
    reads its file."""
    old = _old_layout_thread(restartable, script)
    tid, rule_id, owner_dir, system_dir = old.tid, old.rule_id, old.owner_dir, old.system_dir

    client = restartable.start()  # the migration runs in this startup
    try:
        studio = _studio_of(client, restartable.tmp)
        assert (owner_dir / "user-data" / "outputs" / "report.md").read_text() == SECRET, "the startup did not move the files to the owner"
        assert not system_dir.exists()
        report = restartable.tmp / "home" / "migrations" / "automation-threads-to-owner.jsonl"
        [entry] = [json.loads(line) for line in report.read_text().splitlines()]
        assert (entry["thread_id"], entry["action"], entry["owner"]) == (tid, "moved", studio.user_id)

        # The automation's next firing (the engine's own injection, on the
        # rule's thread: the same minute's cron firing is already spent) finds
        # its file.
        engine = _engine_noting(studio)
        assert engine.loop.runner.threads.thread_of(rule_id) == tid, "the rule did not keep its thread"
        script.steps.append(_read_report(tid))
        engine.loop.runner.injector.inject(tid, rule_id, "Read your last report.", firing_id="fire-after-restart")
        assert any(SECRET in r for r in _tool_results(studio, tid)), "the next firing did not see the moved file"
    finally:
        client.__exit__(None, None, None)

    client = restartable.start()  # and again: nothing more to do
    try:
        assert (owner_dir / "user-data" / "outputs" / "report.md").read_text() == SECRET
        assert len(report.read_text().splitlines()) == 1, "a rerun reported (or moved) something again"
    finally:
        client.__exit__(None, None, None)


def test_the_startup_migration_never_moves_a_thread_that_is_not_an_automations(restartable) -> None:
    """A system-owned thread that no automation record names (a channel's,
    say) keeps its files where they are."""
    from app.gateway.trigger_engine_wiring import engine_request_headers

    client = restartable.start()
    try:
        studio = _studio_of(client, restartable.tmp)
        body = json.dumps({"metadata": {}}).encode()
        resp = client.post("/api/threads", content=body, headers=engine_request_headers("POST", "/api/threads", body))
        assert resp.status_code in (200, 201), resp.text
        tid = resp.json()["thread_id"]
        owner_dir, system_dir = _dirs(studio, tid)
        (system_dir / "user-data").mkdir(parents=True)
        (system_dir / "user-data" / "note.md").write_text("channel")
    finally:
        client.__exit__(None, None, None)

    client = restartable.start()
    try:
        assert (system_dir / "user-data" / "note.md").read_text() == "channel"
        assert not owner_dir.exists()
    finally:
        client.__exit__(None, None, None)


def test_the_startup_migration_never_moves_under_a_firing(restartable, script) -> None:  # noqa: F811
    """A firing in progress (any worker) holds the rule map's firing lock: the
    startup migration does not move a thread under it, and finishes at the
    next startup."""
    from app.trigger_engine.threads import RuleThreadMap

    old = _old_layout_thread(restartable, script)
    rule_map = RuleThreadMap(path=restartable.tmp / "triggers" / "threads.json", create_thread=lambda rule: "")

    with rule_map.firing_lock() as held:
        assert held
        client = restartable.start()
        client.__exit__(None, None, None)
    assert (old.system_dir / "user-data" / "outputs" / "report.md").read_text() == SECRET, "moved under a firing"
    assert not old.owner_dir.exists()

    client = restartable.start()
    client.__exit__(None, None, None)
    assert (old.owner_dir / "user-data" / "outputs" / "report.md").read_text() == SECRET
    assert not old.system_dir.exists()


def test_a_lead_automations_thread_record_is_still_kept_up_to_date(studio, script, caplog) -> None:  # noqa: F811
    """The run is the owner's, its thread the system's: the run still keeps
    the thread's record (its title, its status) as before #133, and does not
    try to create the record again."""
    import logging

    _rules_file(studio)
    engine = _engine(studio)
    _schedule(studio, agent="lead_agent")
    with caplog.at_level(logging.WARNING, logger="app.gateway.services"):
        _cycle(engine)
    tid = _thread_of(engine)

    row = studio.client.portal.call(lambda: studio.client.app.state.thread_store.get(tid, user_id=None))
    assert row["display_name"] == "A title", row
    assert row["status"] == "idle", row
    assert not [r for r in caplog.records if "Failed to upsert thread_meta" in r.getMessage()]


# -- long-term memory stays as on main: the system user's -----------------------

OWNER_FACT = "OWNER-PRIVATE-FACT-91ab: the owner's salary negotiation is on Friday"
LEARNED = "LEARNED-FACT-5d2e: something the run read"


@pytest.fixture
def memory_studio(tmp_path, monkeypatch):
    """`studio` with long-term memory ON (the default in a real install), the
    owner signed in, and the memory updater's model scripted to learn LEARNED
    from whatever conversation it is given."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from studio_app import configure_studio, fresh_app

    import app.gateway.deps as deps
    import omniharness.agents.memory.updater as updater
    from omniharness.agents.memory.queue import get_memory_queue, reset_memory_queue
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    configure_studio(tmp_path, monkeypatch, memory=True)
    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(deps, "_cached_repo", None)
    learned = json.dumps({"newFacts": [{"content": LEARNED, "category": "context", "confidence": 0.9}]})
    monkeypatch.setattr(updater, "create_chat_model", lambda *a, **k: GenericFakeChatModel(messages=iter([AIMessage(content=learned)] * 5)))
    reset_memory_queue()
    with TestClient(fresh_app()) as client:
        assert client.post("/api/v1/auth/initialize", json={"email": "owner@example.com", "password": "Str0ng!Pass99"}).status_code in (200, 201)
        if client.cookies.get("csrf_token"):
            client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
        studio = _studio_of(client, tmp_path)
        from omniharness.agents.memory.updater import create_memory_fact

        create_memory_fact(OWNER_FACT, confidence=0.9, user_id=studio.user_id)
        studio.flush = get_memory_queue().flush
        yield studio
    get_memory_queue().clear()
    reset_memory_queue()
    reset_app_config()
    reset_extensions_config()


def _memory_facts(user_id: str) -> list[str]:
    from omniharness.agents.memory.updater import reload_memory_data

    return [f.get("content") for f in reload_memory_data(user_id=user_id).get("facts", [])]


def _owner_chat(studio) -> None:
    c = studio.client
    tid = c.post("/api/threads", json={}).json()["thread_id"]
    body = {"assistant_id": "lead_agent", "input": {"messages": [{"role": "human", "content": "What is on this week?"}]}}
    resp = c.post(f"/api/threads/{tid}/runs/wait", json=body)
    assert resp.status_code == 200, resp.text


def test_a_lead_automation_never_sees_the_owners_memory(memory_studio, script) -> None:  # noqa: F811
    studio = memory_studio
    _rules_file(studio)
    engine = _engine(studio)
    _schedule(studio, agent="lead_agent")
    _cycle(engine)

    assert engine.runs() and script.prompts, "the automation did not run"
    assert not any(OWNER_FACT in p for p in script.prompts), "the owner's memory was put in an automation's prompt"

    # The control: the owner's own chat does see it.
    script.prompts.clear()
    _owner_chat(studio)
    assert any(OWNER_FACT in p for p in script.prompts), "the owner's chat did not see the owner's memory: the check above proves nothing"


def test_a_lead_automation_never_writes_the_owners_memory(memory_studio, script) -> None:  # noqa: F811
    from omniharness.runtime.user_context import DEFAULT_USER_ID

    studio = memory_studio
    _rules_file(studio)
    engine = _engine(studio)
    _schedule(studio, agent="lead_agent")
    _cycle(engine)
    studio.flush()

    assert LEARNED not in _memory_facts(studio.user_id), "an automation's conversation became a fact in the owner's memory"
    assert LEARNED in _memory_facts(DEFAULT_USER_ID), "the automation's memory did not go to the system user, as on main"


def test_the_owners_own_chat_still_writes_the_owners_memory(memory_studio, script) -> None:  # noqa: F811
    studio = memory_studio
    _owner_chat(studio)
    studio.flush()
    assert LEARNED in _memory_facts(studio.user_id)


def test_a_request_cannot_choose_whose_memory_a_run_uses(memory_studio, script) -> None:  # noqa: F811
    """The memory override is server-owned: an owner's chat naming the system
    user's memory in every container still reads and writes the owner's."""
    from omniharness.runtime.user_context import DEFAULT_USER_ID, MEMORY_USER_KEY

    studio = memory_studio
    c = studio.client
    tid = c.post("/api/threads", json={}).json()["thread_id"]
    forged = {MEMORY_USER_KEY: DEFAULT_USER_ID}
    body = {"assistant_id": "lead_agent", "input": {"messages": [{"role": "human", "content": "hello"}]}, "context": dict(forged), "metadata": dict(forged), "config": {"configurable": {"thread_id": tid, **forged}}}
    assert c.post(f"/api/threads/{tid}/runs/wait", json=body).status_code == 200
    studio.flush()
    assert any(OWNER_FACT in p for p in script.prompts)
    assert LEARNED in _memory_facts(studio.user_id) and LEARNED not in _memory_facts(DEFAULT_USER_ID)


# -- a lost thread record is recreated as the system's ------------------------


def test_a_scheduled_run_that_recreates_a_lost_thread_record_makes_it_the_systems(studio, script) -> None:  # noqa: F811
    """delete_thread_everywhere can delete a thread's record and then refuse
    (ThreadsBusy), leaving the rule mapped to it. A run that then recreates
    the record (the stateless /api/runs route allows a thread with no record;
    the thread routes refuse one) makes it the REQUEST principal's (the
    system user's, for the engine), never the run user's (the owner, since
    #133): otherwise every later firing on that thread would be refused."""
    from app.gateway.trigger_engine_wiring import engine_request_headers
    from omniharness.runtime.user_context import DEFAULT_USER_ID

    _rules_file(studio)
    engine = _engine(studio)
    rule_id = _schedule(studio, agent="lead_agent")["rule_id"]
    _cycle(engine)
    tid = _thread_of(engine)
    store = studio.client.app.state.thread_store
    studio.client.portal.call(lambda: store.delete(tid, user_id=None))

    # A scheduled run on the thread, by the engine's credential, on the route
    # that accepts a thread with no record.
    body = {
        "assistant_id": "lead_agent",
        "input": {"messages": [{"role": "human", "content": "Again."}]},
        "config": {"configurable": {"thread_id": tid, "turn_provenance": "synthetic-trigger", "trigger_rule_id": rule_id, "trigger_firing_id": "fire-2"}},
        "metadata": {"turn_provenance": "synthetic-trigger", "trigger_rule_id": rule_id, "trigger_firing_id": "fire-2"},
    }
    content = json.dumps(body).encode()
    resp = studio.client.post("/api/runs/wait", content=content, headers=engine_request_headers("POST", "/api/runs/wait", content))
    assert resp.status_code == 200, resp.text
    row = studio.client.portal.call(lambda: store.get(tid, user_id=None))
    assert row is not None and row["user_id"] == DEFAULT_USER_ID, row

    # The engine's next firing on that thread still runs.
    engine.loop.runner.injector.inject(tid, rule_id, "Once more.", firing_id="fire-3")
    assert len([c for c in engine.calls if c[1] == f"/api/threads/{tid}/runs/wait"]) == 2


# -- the migration's record-owner filter, through a restart ---------------------


def test_an_automation_thread_whose_record_names_a_person_is_not_moved(restartable, script) -> None:  # noqa: F811
    """An automation-ledgered thread whose record names a PERSON (not the
    system user) keeps its files where they are: the migration only moves
    threads the system user owns."""
    from sqlalchemy import update

    from omniharness.persistence.engine import get_session_factory
    from omniharness.persistence.thread_meta.model import ThreadMetaRow

    old = _old_layout_thread(restartable, script)
    client = restartable.start()
    try:
        person = _studio_of(client, restartable.tmp).user_id

        async def give_to_person():
            async with get_session_factory()() as session:
                await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == old.tid).values(user_id=person))
                await session.commit()

        client.portal.call(give_to_person)
        # This startup already moved it (the record still named the system
        # user then): put the old layout back for the next one.
        if old.owner_dir.exists():
            import shutil

            shutil.move(str(old.owner_dir), str(old.system_dir))
    finally:
        client.__exit__(None, None, None)

    client = restartable.start()
    client.__exit__(None, None, None)
    assert (old.system_dir / "user-data" / "outputs" / "report.md").read_text() == SECRET, "moved a thread whose record names a person"
    assert not old.owner_dir.exists()
