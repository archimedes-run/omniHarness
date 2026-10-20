"""T6: the code must be shown before it can be approved (#59).

``GET /servers/{id}/approval`` returns the full code, its hash, the outbound
hosts, the tools (all proposed at Tier 3) and a single-use view token;
``POST /enable`` refuses without a valid one.
"""

from __future__ import annotations

from mcp_build_helpers import CODE_V1, CODE_V2, enable, server, submit, wait_for

from omniharness.persistence.mcp_server.approval import code_sha256


def _post(gw, sid, sha, token):
    return gw.client.post(f"/api/mcp-studio/servers/{sid}/enable", json={"code_sha256": sha, "view_token": token})


def test_the_packet_shows_code_hash_hosts_and_tools(built) -> None:
    gw, sid, _, _ = built
    packet = gw.client.get(f"/api/mcp-studio/servers/{sid}/approval").json()
    assert packet["source_code"] == CODE_V1
    assert packet["code_sha256"] == code_sha256(CODE_V1)
    assert packet["egress_hosts"] == []
    assert [(t["name"], t["proposed_tier"]) for t in packet["tools"]] == [("whoami", 3)]
    assert packet["view_token"] and packet["expires_in_seconds"] == 900


def test_enable_without_a_view_token_is_refused(built) -> None:
    gw, sid, runner, _ = built
    resp = _post(gw, sid, server(gw, sid)["code_sha256"], "")
    assert resp.status_code == 409 and "Open the code first" in resp.text
    assert runner.ran() == []


def test_an_expired_token_is_refused(built) -> None:
    gw, sid, _, manager = built
    now = [1000.0]
    manager.view_tokens._clock = lambda: now[0]
    token = gw.client.get(f"/api/mcp-studio/servers/{sid}/approval").json()["view_token"]
    now[0] += 901
    resp = _post(gw, sid, code_sha256(CODE_V1), token)
    assert resp.status_code == 409 and "expired" in resp.text


def test_a_token_for_other_code_is_refused(built) -> None:
    gw, sid, _, _ = built
    token = gw.client.get(f"/api/mcp-studio/servers/{sid}/approval").json()["view_token"]
    submit(gw, sid, CODE_V2)  # the code changes after it was shown
    resp = _post(gw, sid, code_sha256(CODE_V2), token)
    assert resp.status_code == 409 and "changed" in resp.text


def test_a_token_issued_to_another_user_is_refused(built) -> None:
    gw, sid, _, manager = built
    token, _ = manager.view_tokens.issue(server_id=sid, user_id="someone-else", code_sha256=code_sha256(CODE_V1))
    resp = _post(gw, sid, code_sha256(CODE_V1), token)
    assert resp.status_code == 409 and "not yours" in resp.text


def test_a_token_for_another_server_is_refused(built) -> None:
    gw, sid, _, manager = built
    token, _ = manager.view_tokens.issue(server_id="another-server", user_id=gw.user_id, code_sha256=code_sha256(CODE_V1))
    resp = _post(gw, sid, code_sha256(CODE_V1), token)
    assert resp.status_code == 409 and "not yours" in resp.text


def test_a_token_is_single_use(built) -> None:
    gw, sid, runner, _ = built
    token = gw.client.get(f"/api/mcp-studio/servers/{sid}/approval").json()["view_token"]
    first = _post(gw, sid, code_sha256(CODE_V1), token)
    assert first.status_code == 200, first.text
    wait_for(gw, sid, {"enabled", "turn_on_failed"})
    again = _post(gw, sid, code_sha256(CODE_V1), token)
    assert again.status_code == 409 and "already been used" in again.text


def test_approval_records_the_tiers_set_on_the_screen(built) -> None:
    gw, sid, _, _ = built
    assert enable(gw, sid, tiers={"whoami": 1}).status_code == 200
    wait_for(gw, sid, {"enabled"})
    row = gw.client.portal.call(lambda: gw.app.state.mcp_server_repo.get(sid, user_id=gw.user_id))
    assert row["approval"]["tool_tiers"] == {"whoami": 1}
    # An unknown tool or a tier outside 1-3 is refused.
    submit(gw, sid, CODE_V1 + "\n# touched\n")
    assert enable(gw, sid, tiers={"nope": 1}).status_code == 400
    assert enable(gw, sid, tiers={"whoami": 7}).status_code == 400
