"""When each tool source last worked (Feature 006, two-stage integration status).

"Connected" is what Composio REPORTS; "Live · last worked <time>" needs a tool
call from that source to have come back without error. These prove the record
is made at the tool-call chokepoint, kept per source and per user, never
counted for a call the policy blocked, and read back through the production
gateway (`create_app()` and its lifespan).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

from app.gateway.tool_sources import describe_tool_sources
from omniharness.agents.middlewares.tool_source_health_middleware import ToolSourceHealthMiddleware, call_outcome
from omniharness.persistence.tool_source_health import LOCAL_OWNER, SourceHealth
from omniharness.tools.source_tags import source_of, tag_source


@tool
def list_events(day: str) -> str:
    """List events."""
    return day


class FakeRepo:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def record_success(self, *, owner_id: str, source_id: str) -> None:
        self.calls.append(("ok", owner_id, source_id))

    async def record_failure(self, *, owner_id: str, source_id: str, error: str) -> None:
        self.calls.append(("fail", owner_id, source_id, error))


def _request(t):
    return SimpleNamespace(tool=t, tool_call={"name": t.name if t else "x", "id": "c1", "args": {}})


def _ok(_req):
    async def run():
        return ToolMessage(content="3 events", tool_call_id="c1", name="list_events")

    return run()


# ---- tagging ----------------------------------------------------------------


def test_a_tool_carries_its_source_and_owner():
    t = list_events.model_copy()
    assert source_of(t) is None
    tag_source(t, "connector:GOOGLECALENDAR", "u1")
    assert source_of(t) == ("connector:GOOGLECALENDAR", "u1")


# ---- the chokepoint ---------------------------------------------------------


@pytest.mark.anyio
async def test_a_call_that_returns_without_error_is_recorded_as_working():
    repo, t = FakeRepo(), list_events.model_copy()
    tag_source(t, "connector:GMAIL", "u1")
    mw = ToolSourceHealthMiddleware(repo_factory=lambda: repo)
    await mw.awrap_tool_call(_request(t), _ok)
    assert repo.calls == [("ok", "u1", "connector:GMAIL")]


@pytest.mark.anyio
async def test_an_error_message_and_an_exception_are_both_failures():
    repo, t = FakeRepo(), list_events.model_copy()
    tag_source(t, "local:github")
    mw = ToolSourceHealthMiddleware(repo_factory=lambda: repo)

    async def error_message(_req):
        return ToolMessage(content="Error: 401 Bad credentials", tool_call_id="c1", status="error")

    await mw.awrap_tool_call(_request(t), error_message)

    async def raises(_req):
        raise RuntimeError("connection reset")

    with pytest.raises(RuntimeError):
        await mw.awrap_tool_call(_request(t), raises)

    assert repo.calls == [
        ("fail", LOCAL_OWNER, "local:github", "Error: 401 Bad credentials"),
        ("fail", LOCAL_OWNER, "local:github", "RuntimeError: connection reset"),
    ]


@pytest.mark.anyio
async def test_a_built_in_tool_has_no_source_and_is_not_recorded():
    repo = FakeRepo()
    mw = ToolSourceHealthMiddleware(repo_factory=lambda: repo)
    await mw.awrap_tool_call(_request(list_events.model_copy()), _ok)
    assert repo.calls == []


@pytest.mark.anyio
async def test_a_recording_failure_never_breaks_the_call():
    class Broken(FakeRepo):
        async def record_success(self, **_):
            raise OSError("disk full")

    t = list_events.model_copy()
    tag_source(t, "local:github")
    result = await ToolSourceHealthMiddleware(repo_factory=Broken).awrap_tool_call(_request(t), _ok)
    assert result.content == "3 events"


def test_outcome_reads_the_message_status():
    assert call_outcome(ToolMessage(content="x", tool_call_id="1")) == (True, "")
    assert call_outcome(ToolMessage(content="boom", tool_call_id="1", status="error")) == (False, "boom")


def test_it_sits_inside_the_error_handler_and_the_policy_layer():
    """First-defined is outermost. The error handler is appended before it (so
    it sees a failing call's exception), and the policy layer last (outermost:
    a call the policy blocks never reaches it, and is not a source failure)."""
    from omniharness.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware, build_lead_runtime_middlewares
    from omniharness.config import get_app_config

    chain = build_lead_runtime_middlewares(app_config=get_app_config(), lazy_init=True)
    names = [type(m).__name__ for m in chain]
    health = names.index("ToolSourceHealthMiddleware")
    assert names.index(ToolErrorHandlingMiddleware.__name__) < health
    assert health < len(names) - 1, "the policy layer (or its refusal) must stay outermost, after it"


# ---- what the gateway reports -------------------------------------------------


def test_the_view_carries_last_worked_and_a_redacted_last_error():
    at = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    view = describe_tool_sources(
        servers={"github": SimpleNamespace(enabled=True)},
        last_loads={"github": SimpleNamespace(loaded=True, tool_count=3, error=None)},
        connector_toolkits=[{"slug": "GMAIL", "name": "Gmail"}],
        authorised={"GMAIL"},
        selected=None,
        health={
            "connector:GMAIL": SourceHealth(last_success_at=at, last_failure_at=None, last_error=None),
            "local:github": SourceHealth(last_success_at=None, last_failure_at=at, last_error="401 token ghp_abcdefghijklmnopqrstuvwxyz0123456789"),
        },
    )
    by = {s.id: s for s in view.sources}
    assert by["connector:GMAIL"].last_success_at == at
    assert by["local:github"].last_success_at is None
    assert by["local:github"].last_failure_at == at
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in (by["local:github"].last_error or "")


def test_without_a_record_nothing_is_claimed():
    view = describe_tool_sources(servers={}, last_loads={}, connector_toolkits=[{"slug": "GMAIL", "name": "Gmail"}], authorised={"GMAIL"}, selected=None, health=None)
    gmail = next(s for s in view.sources if s.id == "connector:GMAIL")
    assert gmail.last_success_at is None and gmail.last_failure_at is None


# ---- through the production composition root ---------------------------------


def test_a_call_recorded_at_the_chokepoint_is_read_back_by_the_gateway(gateway):
    """The middleware's default repository (the runtime's own session factory)
    and the gateway's (app.state, registered by the lifespan) are the same
    table: a success recorded by one is reported by /api/tool-sources."""
    t = list_events.model_copy()
    tag_source(t, "local:session-watcher")
    mw = ToolSourceHealthMiddleware()

    async def call():
        await mw.awrap_tool_call(_request(t), _ok)

    gateway.client.portal.call(call)

    resp = gateway.client.get("/api/tool-sources")
    assert resp.status_code == 200, resp.text
    watcher = next(s for s in resp.json()["sources"] if s["id"] == "local:session-watcher")
    assert watcher["last_success_at"] is not None
    assert watcher["last_failure_at"] is None
    assert gateway.app.state.tool_source_health_repo is not None


def test_a_connector_record_is_the_users_own(gateway):
    """Connectors run per user: another user's working Gmail says nothing about
    this user's. Local servers are shared, so their record is everyone's."""
    repo = gateway.app.state.tool_source_health_repo

    async def seed():
        await repo.record_success(owner_id="someone-else", source_id="connector:GMAIL")
        await repo.record_failure(owner_id=LOCAL_OWNER, source_id="local:github", error="ConnectError: refused\nTraceback ...")
        return await repo.for_user(user_id="me"), await repo.for_user(user_id="someone-else")

    mine, theirs = gateway.client.portal.call(seed)
    assert "connector:GMAIL" not in mine
    assert theirs["connector:GMAIL"].last_success_at is not None
    assert mine["local:github"].last_error == "ConnectError: refused"


# ---- where tools are assembled ------------------------------------------------


def test_local_mcp_tools_are_tagged_with_their_server_at_assembly():
    from unittest.mock import patch

    from omniharness.tools import tools as tools_mod

    class FakeTool:
        def __init__(self, name):
            self.name, self.group, self.metadata = name, None, None

    class Ext:
        def get_enabled_mcp_servers(self):
            return {"filesystem": object(), "github": object(), "composio-gmail": object()}

    cached = [FakeTool("filesystem_read_file"), FakeTool("github_list_repos"), FakeTool("composio-gmail_GMAIL_SEND")]
    config = SimpleNamespace(tools=[], skill_evolution=None, models=[SimpleNamespace(name="m")], get_model_config=lambda name: SimpleNamespace(supports_vision=False), tool_search=SimpleNamespace(enabled=False), acp_agents={})
    with (
        patch.object(tools_mod, "is_host_bash_allowed", return_value=True),
        patch("omniharness.mcp.cache.get_cached_mcp_tools", return_value=cached),
        patch("omniharness.config.extensions_config.ExtensionsConfig.from_file", return_value=Ext()),
    ):
        tools = tools_mod.get_available_tools(app_config=config, selected_sources={"local:github"})
    by = {t.name: source_of(t) for t in tools}
    assert by["filesystem_read_file"] == ("local:filesystem", LOCAL_OWNER)
    assert by["github_list_repos"] == ("local:github", LOCAL_OWNER)
    assert "composio-gmail_GMAIL_SEND" not in by


@pytest.mark.anyio
async def test_connector_tools_are_tagged_with_their_toolkit_and_user():
    from unittest.mock import patch

    from omniharness.tools import connector_tools as ct

    t = list_events.model_copy()

    class Client:
        def __init__(self, *_a, **_k):
            pass

        async def get_tools(self):
            return [t]

    with (
        patch.object(ct, "_api_key", return_value="k"),
        patch.object(ct, "_active_accounts_for_user", return_value={"GMAIL": "acct-1"}),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", Client),
    ):
        tools = await ct._load_connector_tools_async("u1", {"GMAIL"})
    assert [source_of(x) for x in tools] == [("connector:GMAIL", "u1")]
