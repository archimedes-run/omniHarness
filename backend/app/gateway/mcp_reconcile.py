"""Startup reconcile and the one-time retirement (Feature 006, #59, plan §9).

Two jobs, both reported (on the Build board, through the audit table), never
silent:

1. **Retirement (once, the user's answer to Q4).** Built servers turned on
   before approvals were bound to code ran as root, on the default bridge,
   published on 0.0.0.0 and with their keys in ``-e``. For each such legacy
   container (named ``omni-mcp-<12 hex>``, without the builder's labels):

   a. an audit row is written FIRST (names only: no values, no key hints),
   b. its ``server.py`` is recovered with ``docker create`` + ``docker cp``,
      never started, and kept: in the audit row, and as a ``retired`` server
      row the user can test and approve under the new flow,
   c. the container and its image are removed,
   d. the ``extensions_config.json`` entry pointing at its port is removed.

   Then every ``mcp_secrets`` row whose server no longer exists is deleted
   (after an audit row naming the key names), and the database is vacuumed.
   A marker row makes the job run once; it is idempotent anyway.

2. **Reconcile (every start).** A running built server whose image is not
   the approved code (or whose server row is gone) is turned off; one that
   came back after a Docker restart (its tmpfs is empty) gets its files again.
"""

from __future__ import annotations

import io
import json
import logging
import re
import tarfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select, text

from app.gateway.mcp_docker import DockerRunner
from app.gateway.mcp_names import slugify
from omniharness.persistence.mcp_secrets.model import McpSecretRow
from omniharness.persistence.mcp_server.approval import code_sha256
from omniharness.persistence.mcp_server.audit_model import McpBuildAuditRow
from omniharness.persistence.mcp_server.model import McpServerRow

logger = logging.getLogger(__name__)

RETIREMENT_MARKER = "retirement-2026-10"
ACTOR = "system:startup-reconcile"


def _legacy_name(prefix: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(prefix)}[0-9a-f]{{12}}$")


class Reconciler:
    def __init__(self, *, session_factory, runner: DockerRunner, prefix: str, config_path: Path | None, manager=None) -> None:
        self._sf = session_factory
        self._runner = runner
        self._prefix = prefix
        self._config_path = config_path
        self._manager = manager
        self.messages: list[str] = []

    # -- audit ------------------------------------------------------------

    async def _audit(self, event: str, *, server_id: str | None = None, name: str | None = None, details: dict | None = None) -> None:
        async with self._sf() as session:
            session.add(McpBuildAuditRow(id=uuid.uuid4().hex, at=datetime.now(UTC), actor=ACTOR, event=event, server_id=server_id, name=name, details=details or {}))
            await session.commit()

    async def _done_before(self) -> bool:
        async with self._sf() as session:
            row = (await session.execute(select(McpBuildAuditRow.id).where(McpBuildAuditRow.event == RETIREMENT_MARKER))).first()
        return row is not None

    # -- docker -----------------------------------------------------------

    async def _legacy_containers(self) -> list[dict]:
        rc, out, _ = await self._runner.run(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=30.0)
        found = []
        pattern = _legacy_name(self._prefix)
        for line in out.splitlines() if rc == 0 else []:
            try:
                info = json.loads(line)
            except ValueError:
                continue
            name = info.get("Names", "")
            if not pattern.match(name) or "omni.mcp.role=" in (info.get("Labels") or ""):
                continue
            rc2, detail, _ = await self._runner.run(["docker", "inspect", name, "--format", "{{json .}}"], timeout=30.0)
            try:
                found.append(json.loads(detail)) if rc2 == 0 else None
            except ValueError:
                continue
        return found

    async def _recover_code(self, image: str) -> str | None:
        """server.py from the image, through a container that is created and
        copied from, never started."""
        tmp = f"{self._prefix}recover-{uuid.uuid4().hex[:8]}"
        rc, _, _ = await self._runner.run(["docker", "create", "--pull=never", "--name", tmp, "--network", "none", image, "true"], timeout=60.0)
        if rc != 0:
            return None
        try:
            for path in ("/app/server.py",):
                rc, data, _ = await self._runner.run_bytes(["docker", "cp", f"{tmp}:{path}", "-"], timeout=60.0)
                if rc != 0 or not data:
                    continue
                with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                    member = next((m for m in tar.getmembers() if m.isfile()), None)
                    if member is not None:
                        return tar.extractfile(member).read().decode("utf-8", errors="replace")  # type: ignore[union-attr]
            return None
        finally:
            await self._runner.run(["docker", "rm", "-f", tmp], timeout=30.0)

    # -- config -----------------------------------------------------------

    def _config(self) -> dict:
        if self._config_path is None or not Path(self._config_path).exists():
            return {}
        try:
            data = json.loads(Path(self._config_path).read_text(encoding="utf-8"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _entries_on_port(self, port: str) -> list[str]:
        servers = self._config().get("mcpServers") or {}
        return [k for k, v in servers.items() if isinstance(v, dict) and str(v.get("url") or "").rstrip("/").endswith(f":{port}/sse")]

    def _remove_entries(self, keys: list[str]) -> None:
        if not keys or self._config_path is None:
            return
        from omniharness.config.extensions_config import atomic_write_json

        data = self._config()
        for k in keys:
            (data.get("mcpServers") or {}).pop(k, None)
        atomic_write_json(self._config_path, data)

    # -- the jobs ---------------------------------------------------------

    async def _owner_id(self) -> str | None:
        from omniharness.persistence.user.model import UserRow

        async with self._sf() as session:
            row = (await session.execute(select(UserRow.id).where(UserRow.system_role == "admin").order_by(UserRow.created_at))).first()
        return str(row[0]) if row else None

    async def retire(self) -> list[str]:
        """The one-time retirement; returns what it did, in words."""
        if await self._done_before():
            return []
        messages: list[str] = []
        owner = await self._owner_id()
        for info in await self._legacy_containers():
            name = info.get("Name", "").lstrip("/")
            image = (info.get("Config") or {}).get("Image") or info.get("Image")
            env_names = sorted({e.split("=", 1)[0] for e in (info.get("Config") or {}).get("Env") or []} - {"PATH", "LANG", "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256", "MCP_TRANSPORT", "MCP_PORT", "HOME"})
            ports = [b.get("HostPort") for v in ((info.get("HostConfig") or {}).get("PortBindings") or {}).values() for b in (v or [])]
            entries = [k for p in ports if p for k in self._entries_on_port(p)]
            code = await self._recover_code(image) if image else None
            details = {
                "container": name,
                "container_id": info.get("Id"),
                "image": image,
                "env_names": env_names,
                "published_ports": ports,
                "config_entries": entries,
                "code_sha256": code_sha256(code),
                "code": code,
                "why": "started before approvals were bound to code: root, default bridge, 0.0.0.0, keys in -e",
            }
            # Audit FIRST: nothing is removed without its record.
            await self._audit("retired", name=", ".join(entries) or name, details=details)
            if code and owner:
                async with self._sf() as session:
                    session.add(
                        McpServerRow(
                            id=uuid.uuid4().hex,
                            owner_id=owner,
                            name=slugify(entries[0] if entries else name),
                            language="python",
                            description="Retired: built before approvals were bound to code. Test it and approve it to use it again.",
                            status="retired",
                            detected_secrets=[n for n in env_names],
                            approved=False,
                            egress_hosts=[],
                            source_code=code,
                            created_at=datetime.now(UTC),
                            updated_at=datetime.now(UTC),
                        )
                    )
                    await session.commit()
            await self._runner.run(["docker", "rm", "-f", name], timeout=60.0)
            if image:
                await self._runner.run(["docker", "rmi", "-f", image], timeout=120.0)
            self._remove_entries(entries)
            label = entries[0] if entries else name
            kept = "Its code is kept; test and approve it to use it again." if code else "Its code could not be recovered."
            messages.append(f"Retired {label}: started before approvals were bound to code. {kept}")

        # Orphaned secrets: rows whose server no longer exists.
        async with self._sf() as session:
            server_ids = {r[0] for r in (await session.execute(select(McpServerRow.id))).all()}
            rows = (await session.execute(select(McpSecretRow.server_id, McpSecretRow.key_name))).all()
        orphans: dict[str, list[str]] = {}
        for sid, key in rows:
            if sid not in server_ids:
                orphans.setdefault(sid, []).append(key)
        for sid, keys in sorted(orphans.items()):
            await self._audit("orphaned-secrets", server_id=sid, details={"key_names": sorted(keys)})
        if orphans:
            async with self._sf() as session:
                await session.execute(delete(McpSecretRow).where(McpSecretRow.server_id.in_(list(orphans))))
                await session.commit()
            messages.append(f"Deleted {sum(len(v) for v in orphans.values())} stored secret(s) left by {len(orphans)} removed server(s).")
        await self._vacuum()
        await self._audit(RETIREMENT_MARKER, details={"messages": messages})
        return messages

    async def _vacuum(self) -> None:
        engine = getattr(self._sf, "kw", {}).get("bind")
        if engine is None:
            return
        try:
            if engine.dialect.name == "sqlite":
                async with engine.connect() as conn:
                    await conn.execution_options(isolation_level="AUTOCOMMIT")
                    await conn.execute(text("VACUUM"))
            else:
                async with engine.connect() as conn:
                    await conn.execution_options(isolation_level="AUTOCOMMIT")
                    await conn.execute(text("VACUUM FULL mcp_secrets"))
        except Exception:
            logger.exception("VACUUM after the retirement failed")

    async def reconcile(self) -> list[str]:
        """Turn off built servers whose image is not the approved code."""
        messages: list[str] = []
        flt = "label=omni.mcp.role=server"
        rc, out, _ = await self._runner.run(["docker", "ps", "-a", "--filter", flt, "--format", '{{.Names}}|{{.Label "omni.mcp.server"}}|{{.Label "omni.code_sha256"}}'], timeout=30.0)
        for line in out.splitlines() if rc == 0 else []:
            name, server_id, sha = (line.split("|") + ["", "", ""])[:3]
            if not name.startswith(self._prefix):
                continue
            async with self._sf() as session:
                row = await session.get(McpServerRow, server_id) if server_id else None
            if row is not None and row.approved_code_sha256 and row.approved_code_sha256 == sha:
                # Approved and kept: if Docker restarted it (empty tmpfs), it
                # waits for its files; hand them over again (#59).
                if self._manager is not None and server_id:
                    for container in (name, self._manager._names(server_id)["egress"]):
                        outcome = await self._manager.redeliver_with_retries(container, attempts=3)
                        if outcome == "delivered":
                            messages.append(f"Handed {row.name} its files again after a restart.")
                continue
            why = "its server was deleted" if row is None else "it runs code that is not the approved version"
            await self._audit("turned-off", server_id=server_id, name=row.name if row else name, details={"container": name, "code_sha256": sha, "why": why})
            if self._manager is not None and server_id:
                await self._manager._remove_topology(server_id)
            else:
                await self._runner.run(["docker", "rm", "-f", name], timeout=30.0)
            messages.append(f"Turned off {row.name if row else name}: {why}.")
        return messages


async def recent_events(session_factory, limit: int = 20) -> list[dict]:
    """What the reconcile and retirement did, newest first (names only)."""
    async with session_factory() as session:
        rows = (await session.execute(select(McpBuildAuditRow).where(McpBuildAuditRow.event.in_(("retired", "orphaned-secrets", "turned-off"))).order_by(McpBuildAuditRow.at.desc()).limit(limit))).scalars().all()
    out = []
    for r in rows:
        d = dict(r.details or {})
        d.pop("code", None)  # the recovered code is kept in the row, not shown in a list
        out.append({"at": r.at.isoformat() if r.at else None, "event": r.event, "server_id": r.server_id, "name": r.name, "details": d})
    return out
