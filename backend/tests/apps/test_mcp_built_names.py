"""T8: built servers live under built/, never collide, and start at Tier 3 (#59).

A built server named `github` used to overwrite the real `github` entry in
extensions_config.json and inherit `github_*` Tier 1 rules.
"""

from __future__ import annotations

import json

from mcp_build_helpers import CODE_V1, enable, server, submit, wait_for

from app.policy.classify import classify
from app.policy.config import RuleSet
from app.policy.models import ClassificationRule, Tier

GITHUB = {"enabled": True, "type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}


def _config(gw, servers: dict) -> None:
    gw.extensions.write_text(json.dumps({"mcpServers": servers, "skills": {}}, indent=2))


def _rows(gw) -> list[dict]:
    return gw.client.get("/api/mcp-studio/servers").json()["servers"]


def test_a_name_that_reads_as_an_existing_server_is_refused(builder_gateway, monkeypatch) -> None:
    gw = builder_gateway

    async def no_agent(*args, **kwargs):
        return None

    monkeypatch.setattr("app.gateway.routers.mcp_studio.run_agent", no_agent)
    _config(gw, {"github": GITHUB})
    before = len(_rows(gw))
    resp = gw.client.post("/api/mcp-studio/builds", json={"description": "github"})
    assert resp.status_code == 409, resp.text
    assert "github" in resp.json()["detail"]
    for name in ("GitHub", "git_hub", "git-hub", "built__github"):
        r = gw.client.post("/api/mcp-studio/servers", json={"name": name, "description": "issues"})
        assert r.status_code == 409, (name, r.text)
    assert len(_rows(gw)) == before, "no row is created for a refused name"
    # An underscore never survives into a slug.
    ok = gw.client.post("/api/mcp-studio/servers", json={"name": "Issue_Tracker", "description": "issues"})
    assert ok.status_code == 201, ok.text
    assert [s["name"] for s in _rows(gw) if s["id"] == ok.json()["server_id"]] == ["issue-tracker"]


def test_connect_never_overwrites_an_entry_it_does_not_own(built) -> None:
    gw, sid, runner, _ = built
    name = server(gw, sid)["name"]
    # Someone else's entry appears under this server's wire key.
    _config(gw, {"github": GITHUB, f"built__{name}": {"enabled": True, "type": "sse", "url": "http://elsewhere/sse"}})
    before = gw.extensions.read_bytes()
    resp = enable(gw, sid)
    assert resp.status_code == 409, resp.text
    assert "collision" in resp.text or "configured" in resp.text
    assert gw.extensions.read_bytes() == before
    assert runner.ran() == []


def test_approved_server_is_written_under_built_with_its_tiers(built) -> None:
    gw, sid, _, _ = built
    _config(gw, {"github": GITHUB})
    assert enable(gw, sid, tiers={"whoami": 1}).status_code == 200
    s = wait_for(gw, sid, {"enabled", "turn_on_failed"})
    assert s["state"] == "enabled", s
    cfg = json.loads(gw.extensions.read_text())["mcpServers"]
    assert cfg["github"] == GITHUB, "the real github entry is untouched"
    entry = cfg[f"built__{s['name']}"]
    assert entry["server_id"] == sid
    assert entry["built"]["tool_tiers"] == {"whoami": 1}
    assert entry["built"]["display_name"] == f"built/{s['name']}"


def test_prefix_overlap_with_another_built_server_is_refused(built) -> None:
    gw, sid, _, manager = built
    # Another built server `git-hub` exposes tool `x`; this one becomes `git`
    # with tool `hub_x`: both would be `built__git_hub_x` canonically.
    repo = gw.app.state.mcp_server_repo

    async def make_overlap():
        other = await repo.create(name="git-hub", owner_id=gw.user_id, source_code=CODE_V1)
        await repo.update_build_result(other["id"], phase="verified", tools_discovered=[{"name": "x"}], test_results=[], last_verified_at=None, user_id=gw.user_id)
        mine = await repo.get(sid, user_id=gw.user_id)
        return await manager.name_problem({**mine, "name": "git"}, ["hub_x"])

    problem = gw.client.portal.call(make_overlap)
    assert problem and "already registered" in problem, problem


def _rules(*pairs: tuple[str, int]) -> RuleSet:
    return RuleSet(rules=tuple(ClassificationRule(pattern=p, tier=Tier(t)) for p, t in pairs))


def test_built_tools_never_match_shared_rules(tmp_path, monkeypatch) -> None:
    path = tmp_path / "extensions_config.json"
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(path))
    rules = _rules(("*", 1), ("github_get_issue", 1))
    path.write_text(json.dumps({"mcpServers": {}}))
    assert classify("github_get_issue", {}, rules).tier == Tier.TIER_1
    assert classify("built__github_get_issue", {}, rules).tier == Tier.TIER_3

    # The approval screen set get_issue to Tier 1 for built/github only.
    servers = {
        "built__github": {"server_id": "s1", "built": {"code_sha256": "a" * 64, "tool_tiers": {"get_issue": 1}}},
        "built__other": {"server_id": "s2", "built": {"code_sha256": "b" * 64, "tool_tiers": {"get_issue": 3}}},
    }
    path.write_text(json.dumps({"mcpServers": servers}))
    assert classify("built__github_get_issue", {}, rules).tier == Tier.TIER_1
    assert classify("built__github_get-issue", {}, rules).tier == Tier.TIER_1  # canonical names
    # Another built server with the same tool name does not inherit it.
    assert classify("built__other_get_issue", {}, rules).tier == Tier.TIER_3
    assert classify("built__third_get_issue", {}, rules).tier == Tier.TIER_3
    # Unreadable rules: everything Tier 3, built tools too.
    assert classify("built__github_get_issue", {}, RuleSet(unreadable=True)).tier == Tier.TIER_3

    # After a code change the approval record is rewritten without the tier.
    servers["built__github"]["built"]["tool_tiers"] = {}
    path.write_text(json.dumps({"mcpServers": servers}))
    import os

    os.utime(path, ns=(os.stat(path).st_mtime_ns + 1_000_000, os.stat(path).st_mtime_ns + 1_000_000))
    assert classify("built__github_get_issue", {}, rules).tier == Tier.TIER_3


def test_a_hand_written_built_entry_is_not_loaded(monkeypatch) -> None:
    from omniharness.config.extensions_config import ExtensionsConfig
    from omniharness.mcp import load_report
    from omniharness.mcp.tools import _drop_unapproved_built

    cfg = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "built__squatter": {"enabled": True, "type": "sse", "url": "http://x/sse"},
                "built__real": {"enabled": True, "type": "sse", "url": "http://y/sse", "server_id": "s", "built": {"code_sha256": "c" * 64}},
                "github": GITHUB,
            }
        }
    )
    servers = {"built__squatter": {}, "built__real": {}, "github": {}}
    _drop_unapproved_built(cfg, servers)
    assert set(servers) == {"built__real", "github"}
    assert "built__squatter" in load_report.last_loads()


def test_the_config_route_cannot_add_or_rewrite_a_built_entry(built) -> None:
    gw, sid, _, _ = built
    assert enable(gw, sid, tiers={"whoami": 1}).status_code == 200
    s = wait_for(gw, sid, {"enabled"})
    key = f"built__{s['name']}"
    cfg = json.loads(gw.extensions.read_text())["mcpServers"]
    # Adding a built/ server by hand is refused.
    body = {"mcp_servers": {**{k: {"enabled": True, "type": v.get("type", "stdio"), "url": v.get("url")} for k, v in cfg.items()}, "built__mine": {"enabled": True, "type": "sse", "url": "http://x/sse"}}}
    assert gw.client.put("/api/mcp/config", json=body).status_code == 400
    # Switching one off keeps its approval record.
    body = {"mcp_servers": {key: {"enabled": False, "type": "sse", "url": "http://tampered/sse"}}}
    assert gw.client.put("/api/mcp/config", json=body).status_code == 200, "toggle"
    entry = json.loads(gw.extensions.read_text())["mcpServers"][key]
    assert entry["enabled"] is False
    assert entry["url"] == cfg[key]["url"]
    assert entry["built"]["tool_tiers"] == {"whoami": 1}
    _ = submit  # (kept for symmetry with the other suites)
