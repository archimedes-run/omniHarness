"""Re-delivery after a restart is only for the APPROVED code (#59).

Docker faked: the container's labels say which code it runs."""

from __future__ import annotations

import json

from mcp_build_helpers import enable, wait_for
from mcp_fakes import Call

from omniharness.persistence.mcp_server.approval import code_sha256


def _inspect(name: str, labels: dict, ip: str) -> str:
    return json.dumps({"Name": "/" + name, "Config": {"Labels": labels}, "NetworkSettings": {"Networks": {"NET": {"IPAddress": ip}}}})


def test_files_are_handed_only_to_a_container_running_the_approved_code(built) -> None:
    gw, sid, runner, manager = built
    assert enable(gw, sid).status_code == 200
    wait_for(gw, sid, {"enabled"})
    row = gw.client.portal.call(lambda: gw.app.state.mcp_server_repo.get(sid, user_id=gw.user_id))
    n = manager._names(sid)
    approved = row["approved_code_sha256"]
    other = code_sha256("print('not the approved code')\\n")

    def answer(sha: str):
        async def run(args, *, stdin=None, timeout=120.0):
            runner.calls.append(Call(list(args), stdin))
            line = " ".join(args)
            if args[1] == "container" and args[2] == "inspect":
                target = args[3]
                role = "server" if target == n["server"] else "egress"
                ip = "172.30.0.3" if role == "server" else "172.30.0.2"
                labels = {"omni.mcp.role": role, "omni.mcp.server": sid, "omni.code_sha256": sha if role == "server" else ""}
                return 0, _inspect(target, labels, ip).replace('"NET"', json.dumps(n["net"])), ""
            if "test -e /run/omni/ready" in line:
                return 1, "", ""  # restarted: no files
            return 0, "", ""

        return run

    runner.run = answer(other)
    runner.calls.clear()
    outcome = gw.client.portal.call(lambda: manager.redeliver(n["server"]))
    assert outcome.startswith("refused"), outcome
    assert not any(c.args[1] == "exec" and c.stdin for c in runner.calls), "files were handed to unapproved code"

    runner.run = answer(approved)
    runner.calls.clear()
    assert gw.client.portal.call(lambda: manager.redeliver(n["server"])) == "delivered"
    sent = [c for c in runner.calls if c.args[1] == "exec" and c.stdin]
    assert sent and all("-e" not in c.args[:4] for c in sent)
    assert gw.client.portal.call(lambda: manager.redeliver(n["egress"])) == "delivered"
