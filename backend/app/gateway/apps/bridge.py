"""The bridge: an app's data, read as the owner, projected, cached (Spec 011
FR-009 to FR-015).

A source runs ONLY through its catalog entry: the entry's tool and arguments,
or its in-process reader, with params from the approved manifest. Nothing the
frame or the request sends reaches it.

The order of a read is fixed:

  1. read-only checks (checks.py), every call, before the cache;
  2. the cache, keyed by (owner, app, source, manifest hash), in the shared SQL
     store; fresh enough: answered at once; stale: answered, and refreshed in
     the background; missing: fetched now;
  3. at most one upstream call per source per UPSTREAM_MIN_INTERVAL_S across
     workers (a conditional UPDATE claims it);
  4. the raw result is projected to the declared fields BEFORE anything is
     stored, and dropped. It is never cached, logged or returned.

Bridge results go to the HTTP response and the cache only. This module imports
nothing that reaches a thread, a run, memory or a model (gate:
tests/omni_apps/test_bridge_isolation.py), and nothing here writes anywhere but
the apps cache.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

from app.gateway.apps import catalog
from app.gateway.apps.catalog import Entry, NotConnected, SourceContext, SourceFailed, Unrecognised
from app.gateway.apps.checks import read_only_refusal, rules_in_force
from app.gateway.apps.service import AppRecord, iso

logger = logging.getLogger(__name__)

#: One upstream call per source per this many seconds, whatever the request rate.
UPSTREAM_MIN_INTERVAL_S = 60
#: Bridge requests per app per minute per owner.
REQUESTS_PER_MINUTE = 60
#: How long one upstream read may take.
READ_TIMEOUT_S = 8.0
#: How long a request waits for another worker's in-flight first fetch.
WAIT_FOR_FETCH_S = 10.0
REASON_MAX = 300

#: Background refreshes in flight, held so they are not collected mid-run.
_BACKGROUND: set[asyncio.Task] = set()


class SourceRefused(Exception):
    """A source failed a read-only check: refused, never read."""


def _sanitise(text: str) -> str:
    return " ".join(str(text).split())[:REASON_MAX]


def _reason_for(exc: BaseException, entry: Entry) -> str:
    """Fixed wording: never upstream text, which could carry data."""
    from app.gateway.composio_client import ComposioError

    if isinstance(exc, (SourceFailed, Unrecognised)):
        return _sanitise(str(exc))
    if isinstance(exc, TimeoutError):
        return f"The source did not answer within {int(READ_TIMEOUT_S)} s"
    if isinstance(exc, ComposioError):
        status = re.search(r"HTTP (\d{3})", str(exc))
        if status:
            return f"The connector answered HTTP {status.group(1)}"
        if "larger than" in str(exc):
            return "The connector's answer was too large to read"
        return "The connector reported an error"
    return f"The source could not be read ({type(exc).__name__})"


def arguments_for(entry: Entry, params: dict, now: datetime) -> dict:
    return entry.arguments(params, now) if entry.arguments is not None else {}


def refusal(app_state, entry: Entry | None, params: dict, now: datetime) -> str | None:
    if entry is None:
        return "the source is not in the catalog"
    return read_only_refusal(entry, arguments_for(entry, params, now), rules_in_force(app_state))


async def fetch(app_state, owner_id: str, entry: Entry, spec: dict) -> tuple[str, dict | None, str | None]:
    """(state, projected payload, reason). Runs the source as the owner."""
    now = datetime.now(UTC)
    params = spec["params"]
    reason = refusal(app_state, entry, params, now)
    if reason is not None:
        raise SourceRefused(reason)
    try:
        if entry.kind == "connector":
            from app.gateway.composio_client import execute_read_tool
            from app.gateway.home_sources import _connection

            client, account = await _connection(app_state, owner_id, entry.toolkit)
            if client is None:
                if account == "not-set-up":
                    return "not_connected", None, None
                return "failed", None, _sanitise(account)
            raw: Any = await asyncio.wait_for(
                execute_read_tool(client, slug=entry.tool, connected_account_id=account, user_id=owner_id, arguments=arguments_for(entry, params, now), allowed=catalog.READ_ALLOWLIST),
                READ_TIMEOUT_S,
            )
        else:
            raw = await asyncio.wait_for(entry.read(SourceContext(app_state=app_state, owner_id=owner_id), params, now), READ_TIMEOUT_S)
        projected = entry.project(raw, params, now)
    except NotConnected:
        return "not_connected", None, None
    except SourceRefused:
        raise
    except Exception as exc:  # noqa: BLE001 - any failure is "can't tell", with a fixed reason
        return "failed", None, _reason_for(exc, entry)
    # The raw result goes no further than projection: only `selected` leaves.
    selected = catalog.select(projected, entry, spec["fields"])
    return ("empty" if catalog.is_empty(projected) else "fresh"), selected, None


async def fetch_and_record(app_state, repo, app: AppRecord, name: str) -> None:
    spec = app.sources[name]
    entry = catalog.get_entry(spec["use"])
    try:
        state, data, reason = await fetch(app_state, app.owner_id, entry, spec)
    except SourceRefused as exc:
        state, data, reason = "failed", None, _sanitise(f"Refused: {exc}")
    try:
        await repo.record_answer(
            owner_id=app.owner_id,
            app_id=app.app_id,
            source=name,
            manifest_hash=app.manifest_hash,
            state=state,
            data_json=json.dumps(data, separators=(",", ":")) if data is not None else None,
            reason=reason,
        )
    except Exception as exc:  # noqa: BLE001 - the error's text can carry the data being written
        logger.warning("app %s source %s: the answer could not be stored (%s)", app.app_id, name, type(exc).__name__)


def result(name: str, spec: dict, row: dict | None) -> dict:
    """A SourceResult from a cache row (FR-013)."""
    now = time.time()
    if row is None or row.get("answered_at") is None:
        return {"source": name, "state": "failed", "data": None, "fetched_at": None, "stale": False, "reason": "The source is being read; try again in a moment"}
    state = row["state"]
    data = json.loads(row["data"]) if row.get("data") and state != "not_connected" else None
    fetched = row.get("fetched_at")
    stale = bool(fetched and now - fetched > 2 * spec["refresh_s"]) or (state == "failed" and data is not None)
    return {"source": name, "state": state, "data": data, "fetched_at": iso(fetched), "stale": stale, "reason": row.get("reason") if state == "failed" else None}


def background_tasks() -> list[asyncio.Task]:
    """Background refreshes still in flight (stopped at shutdown)."""
    return list(_BACKGROUND)


async def _quiet(coro) -> None:
    """A background refresh: any error is logged by type only, never by text."""
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("an app background refresh failed (%s)", type(exc).__name__)


def _background(app_state, repo, app: AppRecord, name: str) -> None:
    task = asyncio.create_task(_quiet(fetch_and_record(app_state, repo, app, name)))
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


async def serve(app_state, repo, app: AppRecord, name: str, *, force: bool = False) -> dict:
    """One source's SourceResult. The caller has checked the owner and grant."""
    spec = app.sources[name]
    entry = catalog.get_entry(spec["use"])
    reason = refusal(app_state, entry, spec["params"], datetime.now(UTC))
    if reason is not None:
        raise SourceRefused(reason)
    key = {"owner_id": app.owner_id, "app_id": app.app_id, "source": name, "manifest_hash": app.manifest_hash}
    row = await repo.cache_row(**key)
    answered = row.get("answered_at") if row else None
    due = answered is None or force or time.time() - answered >= spec["refresh_s"]
    if not due:
        return result(name, spec, row)
    claimed = await repo.claim_upstream(**key, min_interval_s=UPSTREAM_MIN_INTERVAL_S)
    if answered is not None and not force:
        if claimed:
            _background(app_state, repo, app, name)
        return result(name, spec, row)
    if claimed:
        await fetch_and_record(app_state, repo, app, name)
    elif answered is None:
        deadline = time.time() + WAIT_FOR_FETCH_S
        while time.time() < deadline:
            await asyncio.sleep(0.2)
            row = await repo.cache_row(**key)
            if row and row.get("answered_at") is not None:
                break
    return result(name, spec, await repo.cache_row(**key))


async def serve_all(app_state, repo, app: AppRecord) -> dict[str, dict]:
    names = list(app.sources)
    answers = await asyncio.gather(*(serve(app_state, repo, app, n) for n in names), return_exceptions=True)
    out: dict[str, dict] = {}
    for name, answer in zip(names, answers, strict=True):
        if isinstance(answer, SourceRefused):
            out[name] = {"source": name, "state": "failed", "data": None, "fetched_at": None, "stale": False, "reason": _sanitise(f"Refused: {answer}")}
        elif isinstance(answer, BaseException):
            logger.warning("app %s source %s could not be served: %s", app.app_id, name, type(answer).__name__)
            out[name] = {"source": name, "state": "failed", "data": None, "fetched_at": None, "stale": False, "reason": "The source could not be served"}
        else:
            out[name] = answer
    return out
