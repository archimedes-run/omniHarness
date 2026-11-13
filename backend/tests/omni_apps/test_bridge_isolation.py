"""App data never reaches a thread, a run, memory or a model (Spec 011 FR-012),
and grants and versions have exactly one writer each (FR-006, FR-007).

Two kinds of check:

  * STATE: after bridge calls whose data carries a marker, the marker is found
    in the apps cache and nowhere else: no other table of the gateway's
    database, no file under the runtime home or the data directory, no log
    line. The raw result's body text is found nowhere at all.
  * STRUCTURE: the apps modules import nothing that reaches thread state,
    runs, memory, agents or models; `create_grant` is called only by the
    approval route; `write_app` only by registration and Restore.
"""

from __future__ import annotations

import ast
import logging
import sqlite3
from pathlib import Path

from _apps_helpers import MARKER, gmail_answer, manifest

BACKEND = Path(__file__).resolve().parents[2]
APPS_MODULES = sorted((BACKEND / "app" / "gateway" / "apps").glob("*.py")) + [BACKEND / "app" / "gateway" / "routers" / "apps.py"]

#: What app data must never be able to reach.
FORBIDDEN_IMPORTS = (
    "langgraph",
    "langchain",
    "omniharness.agents",
    "omniharness.models",
    "omniharness.runtime",
    "omniharness.subagents",
    "omniharness.reflection",
    "omniharness.tools",
    "omniharness.persistence.thread_meta",
    "omniharness.persistence.run",
    "app.run_history",
    "app.channels",
    "app.gateway.routers.threads",
    "app.gateway.routers.thread_runs",
    "app.gateway.routers.runs",
    "app.gateway.routers.memory",
    "app.policy.private_reads",
    "app.trigger_engine.injector",
)
#: Narrow exceptions, each a pure function with no state of its own.
ALLOWED = {
    "omniharness.tools.names",  # canonical tool names for the policy check
    "omniharness.runtime.user_context",  # DEFAULT_USER_ID, to refuse the system user
}


def _imports(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_apps_modules_import_nothing_that_reaches_threads_runs_memory_or_models() -> None:
    assert len(APPS_MODULES) >= 9, APPS_MODULES
    leaks = [(p.name, m) for p in APPS_MODULES for m in _imports(p) if m not in ALLOWED and any(m == f or m.startswith(f + ".") for f in FORBIDDEN_IMPORTS)]
    assert not leaks, leaks


def _calls(name: str) -> list[tuple[str, str]]:
    """(file, enclosing function) of every call to `.name(` under app/ and packages/."""
    found = []
    for root in (BACKEND / "app", BACKEND / "packages"):
        for path in root.rglob("*.py"):
            if ".venv" in path.parts:
                continue
            tree = ast.parse(path.read_text())
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == name:
                        found.append((str(path.relative_to(BACKEND)), fn.name))
    return sorted(set(found))


def test_only_the_approval_button_creates_a_grant() -> None:
    assert _calls("create_grant") == [("app/gateway/routers/apps.py", "approve")]


def test_only_registration_and_restore_write_an_app_version() -> None:
    assert _calls("write_app") == [("app/gateway/apps/registry.py", "register_app"), ("packages/harness/omniharness/config/config_versions.py", "restore_app")]
    assert _calls("restore_app") == [("app/gateway/routers/apps.py", "restore"), ("packages/harness/omniharness/config/config_versions.py", "undo")]


def test_bridge_data_is_in_the_apps_cache_and_nowhere_else(gateway, composio, apps, caplog) -> None:
    # The gateway's own loggers at DEBUG; libraries at the production level
    # (aiosqlite's DEBUG echoes SQL parameters, including the cache write).
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.DEBUG, logger="app")
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer(subject=f"Deal {MARKER}", body="RAW-BODY-NEVER-STORED")
    reg = apps.register(manifest())
    apps.approve(reg.app_id)
    assert MARKER in gateway.client.get(f"/api/apps/{reg.app_id}/data").text
    assert MARKER in gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox", params={"refresh": 1}).text
    gateway.client.get(f"/api/apps/{reg.app_id}/permissions")
    gateway.client.get("/api/apps")

    db = next((gateway.tmp / "data").glob("*.db"))
    hits = []
    with sqlite3.connect(db) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "app_source_cache" in tables and "threads_meta" in tables
        for table in tables:
            for row in conn.execute(f'SELECT * FROM "{table}"'):  # noqa: S608 - table names from sqlite_master
                text = " ".join(str(v) for v in row)
                if "RAW-BODY-NEVER-STORED" in text:
                    hits.append((table, "raw body"))
                if MARKER in text and table != "app_source_cache":
                    hits.append((table, "marker"))
    assert not hits, hits
    for path in gateway.tmp.rglob("*"):
        if path.is_file() and path.suffix not in (".db", ".db-wal", ".db-shm"):
            data = path.read_bytes()
            assert MARKER.encode() not in data and b"RAW-BODY-NEVER-STORED" not in data, path
    assert MARKER not in caplog.text and "RAW-BODY-NEVER-STORED" not in caplog.text


def test_a_bridge_call_creates_no_thread_and_no_run(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    reg = apps.register(manifest())
    apps.approve(reg.app_id)
    db = next((gateway.tmp / "data").glob("*.db"))

    def counts():
        with sqlite3.connect(db) as conn:
            return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in ("threads_meta", "runs", "run_events")}  # noqa: S608

    before = counts()
    gateway.client.get(f"/api/apps/{reg.app_id}/data")
    assert counts() == before
