"""T18: retiring the pre-#59 built server and the orphaned secrets (plan §9).

Against a temporary database and the recording Docker runner, never the live
stack: the legacy container below is a fake answer of `docker ps`.
"""

from __future__ import annotations

import io
import json
import tarfile

import pytest
from mcp_fakes import Call, FakeDockerRunner

from app.gateway.mcp_reconcile import RETIREMENT_MARKER, Reconciler, recent_events

LEGACY = "omni-mcp-c641ac8dc68d"
SECRET_VALUE = "ghp_LEGACYTOKENVALUE0123456789"
CODE = "from mcp.server.fastmcp import FastMCP\nmcp = FastMCP('issues')\n"


def _tar(name: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class LegacyDocker(FakeDockerRunner):
    """docker as it looks with one legacy built server on it."""

    def __init__(self, sequence: list) -> None:
        super().__init__()
        self.sequence = sequence

    async def run(self, args, *, stdin=None, timeout=120.0):
        await super().run(args, stdin=stdin, timeout=timeout)
        self.sequence.append(("docker", " ".join(args[1:4])))
        line = " ".join(args)
        if line.startswith("docker ps -a --format"):
            rows = [{"Names": LEGACY, "Labels": ""}, {"Names": "omni-harness-gateway", "Labels": ""}, {"Names": "omni-mcp-t-somethingelse", "Labels": ""}]
            return 0, "\n".join(json.dumps(r) for r in rows), ""
        if line.startswith(f"docker inspect {LEGACY}"):
            info = {
                "Id": "c641ac8dc68d" * 5,
                "Name": "/" + LEGACY,
                "Image": "sha256:de4d",
                "Config": {"Image": LEGACY, "Env": [f"GITHUB_TOKEN={SECRET_VALUE}", "PATH=/usr/bin", "MCP_PORT=8080"]},
                "HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "18100"}]}},
            }
            return 0, json.dumps(info), ""
        return 0, "", ""

    async def run_bytes(self, args, *, stdin=None, timeout=120.0):
        if args[1] == "cp":
            self.calls.append(Call(list(args), stdin))
            return 0, _tar("server.py", CODE.encode()), ""
        return await super().run_bytes(args, stdin=stdin, timeout=timeout)


@pytest.fixture
def legacy(builder_gateway, monkeypatch):
    gw = builder_gateway
    gw.extensions.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {"enabled": True, "type": "stdio", "command": "npx"},
                    "github-issue-connector": {"enabled": True, "type": "sse", "url": "http://host.docker.internal:18100/sse"},
                    "session-watcher": {"enabled": True, "type": "sse", "url": "http://host.docker.internal:18101/sse"},
                },
                "skills": {},
            }
        )
    )
    repo, vault = gw.app.state.mcp_server_repo, gw.app.state.mcp_secrets_vault

    async def seed():
        keep = await repo.create(name="still-here", owner_id=gw.user_id)
        await vault.store(server_id=keep["id"], owner_id=gw.user_id, key_name="KEEP_ME", plaintext_value="kept-value-1")
        for sid in ("gone1", "gone2"):
            for key in ("GITHUB_TOKEN", "SLACK_TOKEN"):
                await vault.store(server_id=sid, owner_id=gw.user_id, key_name=key, plaintext_value=f"{sid}-{key}-value")
        return keep["id"]

    keep_id = gw.client.portal.call(seed)
    sequence: list = []
    runner = LegacyDocker(sequence)
    rec = Reconciler(session_factory=repo._sf, runner=runner, prefix="omni-mcp-", config_path=gw.extensions)
    original_audit = rec._audit

    async def audit(event, **kw):
        sequence.append(("audit", event))
        await original_audit(event, **kw)

    rec._audit = audit
    return gw, rec, runner, sequence, keep_id


def test_t18_retirement_audits_first_recovers_without_running_and_cleans_up(legacy) -> None:
    gw, rec, runner, sequence, keep_id = legacy
    messages = gw.client.portal.call(rec.retire)

    # Audit first: the retired row exists before anything is removed.
    first_rm = next(i for i, s in enumerate(sequence) if s == ("docker", f"rm -f {LEGACY}"))
    assert ("audit", "retired") in sequence[:first_rm], sequence
    first_delete = sequence.index(("audit", "orphaned-secrets"))
    assert first_delete < sequence.index(("audit", RETIREMENT_MARKER))
    # Recovered with create + cp, never started.
    verbs = [c.args[1] for c in runner.calls]
    assert "create" in verbs and "start" not in verbs
    assert f"rmi -f {LEGACY}" in [" ".join(c.args[1:]) for c in runner.calls]
    # Only the entry on the legacy port is gone.
    servers = json.loads(gw.extensions.read_text())["mcpServers"]
    assert set(servers) == {"github", "session-watcher"}

    events = gw.client.portal.call(lambda: recent_events(gw.app.state.mcp_server_repo._sf))
    retired = next(e for e in events if e["event"] == "retired")
    assert retired["details"]["env_names"] == ["GITHUB_TOKEN"]
    assert SECRET_VALUE not in json.dumps(events)
    orphans = sorted(e["server_id"] for e in events if e["event"] == "orphaned-secrets")
    assert orphans == ["gone1", "gone2"]
    assert all(e["details"]["key_names"] == ["GITHUB_TOKEN", "SLACK_TOKEN"] for e in events if e["event"] == "orphaned-secrets")

    async def after():
        from sqlalchemy import select

        from omniharness.persistence.mcp_secrets.model import McpSecretRow

        async with gw.app.state.mcp_server_repo._sf() as s:
            return sorted((r.server_id, r.key_name) for r in (await s.execute(select(McpSecretRow))).scalars())

    assert gw.client.portal.call(after) == [(keep_id, "KEEP_ME")]
    rows = gw.client.portal.call(lambda: gw.app.state.mcp_server_repo.list_servers(user_id=None))
    retired_row = next(r for r in rows if r["status"] == "retired")
    assert retired_row["source_code"] == CODE and retired_row["approved"] is False
    assert retired_row["name"] == "github-issue-connector"
    assert any(m.startswith("Retired github-issue-connector") for m in messages), messages
    assert any("Deleted 4 stored secret(s) left by 2 removed server(s)" in m for m in messages), messages

    # Idempotent: a second start changes nothing.
    runner.calls.clear()
    assert gw.client.portal.call(rec.retire) == []
    assert runner.calls == []
