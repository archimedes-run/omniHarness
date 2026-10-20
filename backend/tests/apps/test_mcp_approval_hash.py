"""Approval is bound to the code's hash (#59), through the gateway `create_app()` builds.

* T4: code changed after approval is not approved; it can't be deployed or
  enabled with the old hash.
* T5: a failed deploy leaves nothing approved.
* T15: code changed while an approval is turning on (the image is building)
  is caught before `docker run`; nothing runs and nothing is approved.

Docker is the recording fake behind the production `DockerRunner` port.
"""

from __future__ import annotations

import asyncio
import functools
import json
import time

from mcp_build_helpers import CODE_V1, CODE_V2, enable, on_loop, server, submit, wait_for

from omniharness.persistence.mcp_server.approval import code_sha256


def test_t4_code_changed_after_approval_is_not_approved(built) -> None:
    gw, sid, runner, _ = built
    s = server(gw, sid)
    assert s["state"] == "awaiting_approval" and s["approved"] is False
    assert s["code_sha256"] == code_sha256(CODE_V1)

    resp = enable(gw, sid)
    assert resp.status_code == 200, resp.text
    s = wait_for(gw, sid, {"enabled", "turn_on_failed"})
    assert s["state"] == "enabled", s
    assert s["approved"] is True
    assert s["approved_code_sha256"] == code_sha256(CODE_V1)

    # The agent submits new code through the mcp_build path.
    submit(gw, sid, CODE_V2)
    s = server(gw, sid)
    assert s["approved"] is False, s
    assert s["state"] == "awaiting_approval", s
    assert s["state_reason"] == "New code is waiting for your approval; the approved version is still on"
    # The new code's outbound hosts were read from it, not carried over.
    assert "evil.example" in s["egress_hosts"]

    runs_before = len(runner.ran())
    assert gw.client.post(f"/api/mcp-studio/servers/{sid}/deploy").status_code == 403
    resp = enable(gw, sid, sha=code_sha256(CODE_V1))
    assert resp.status_code == 409, resp.text
    assert len(runner.ran()) == runs_before, "nothing may start for unapproved code"


def test_t4_a_stored_approval_for_other_code_is_not_approval(built) -> None:
    """Layer 2: even an approval record left in place (no clear) does not
    approve code with another hash: approval is derived on every read."""
    gw, sid, _, manager = built
    repo = gw.app.state.mcp_server_repo

    async def forge():
        from omniharness.persistence.mcp_server.model import McpServerRow

        async with repo._sf() as session:
            row = await session.get(McpServerRow, sid)
            old = code_sha256("print('some other code')")
            row.approval = {"code_sha256": old, "egress_hosts": list(row.egress_hosts or [])}
            row.approved_code_sha256 = old
            row.approved = True
            await session.commit()

    gw.client.portal.call(forge)
    s = server(gw, sid)
    assert s["approved"] is False, s
    assert gw.client.post(f"/api/mcp-studio/servers/{sid}/deploy").status_code == 403


def test_t5_a_failed_deploy_leaves_nothing_approved(built) -> None:
    gw, sid, runner, _ = built
    runner.results["run"] = (1, "", "port is already allocated")
    sha = server(gw, sid)["code_sha256"]
    resp = enable(gw, sid, sha=sha)
    assert resp.status_code == 200, resp.text
    s = wait_for(gw, sid, {"turn_on_failed", "enabled"})
    assert s["state"] == "turn_on_failed", s
    assert s["approved"] is False
    assert s["approved_code_sha256"] is None
    assert any("approve it again" in step["text"] for step in s["steps"]), s["steps"]
    row = gw.client.portal.call(functools.partial(gw.app.state.mcp_server_repo.get, sid, user_id=gw.user_id))
    assert row["pending_approval"] is None
    assert json.loads(gw.extensions.read_text())["mcpServers"] == {}


def test_t5_a_pending_approval_with_no_container_is_not_approval(built) -> None:
    """A gateway that died mid-deploy leaves a pending approval and no
    container: that reads as not approved."""
    gw, sid, _, manager = built
    sha = server(gw, sid)["code_sha256"]
    on_loop(gw, manager.begin_approval, server_id=sid, user_id=gw.user_id, code_sha256_seen=sha)
    s = server(gw, sid)
    assert s["approved"] is False
    assert gw.client.post(f"/api/mcp-studio/servers/{sid}/connect").status_code == 403


def test_t15_code_changed_while_turning_on_never_runs(built) -> None:
    gw, sid, runner, manager = built
    images = manager._images
    images.hold_build = asyncio.Event()
    images.build_started = asyncio.Event()
    sha = server(gw, sid)["code_sha256"]
    resp = enable(gw, sid, sha=sha)
    assert resp.status_code == 200, resp.text
    deadline = time.monotonic() + 5
    while not images.build_started.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert images.build_started.is_set(), "the deploy never reached docker build"

    # While the image builds, the agent submits new code.
    submit(gw, sid, CODE_V2)
    gw.client.portal.call(images.hold_build.set)

    s = wait_for(gw, sid, {"turn_on_failed", "enabled"})
    assert s["state"] == "turn_on_failed", s
    assert "changed while turning on" in (s["state_reason"] or ""), s
    assert runner.ran() == [], [c.args for c in runner.ran()]
    assert s["approved"] is False and s["approved_code_sha256"] is None
