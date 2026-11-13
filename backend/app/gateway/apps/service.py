"""Apps: reading an app's current version, its status, and the views the
library, permissions page and approval card show (Spec 011 FR-003 to FR-008).

Every word a card or permissions view shows about a source is built here from
the catalog entry, the chosen fields and params. The manifest's `name` is shown
only as the card's title; nothing the app or worker wrote describes access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.gateway.apps.catalog import DATA_SENTENCE, get_entry, refresh_words
from omniharness.config import config_versions as cv


class AppNotFound(LookupError):
    pass


@dataclass(frozen=True)
class AppRecord:
    owner_id: str
    app_id: str
    version: int
    at: str
    snapshot: dict

    @property
    def manifest(self) -> dict:
        return self.snapshot["manifest"]

    @property
    def manifest_hash(self) -> str:
        return self.snapshot["manifest_hash"]

    @property
    def sources(self) -> dict[str, dict]:
        return self.manifest["sources"]

    @property
    def html_url(self) -> str:
        return f"/api/apps/{self.app_id}/versions/{self.version}/app.html"


def iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat() if ts else None


def load_app(owner_id: str, app_id: str, version: int | None = None) -> AppRecord:
    """The app's current version (or `version`), or AppNotFound."""
    try:
        history = cv.app_history(owner_id, app_id)
    except ValueError as exc:  # an invalid id or user id
        raise AppNotFound(app_id) from exc
    if not history:
        raise AppNotFound(app_id)
    chosen = history[-1] if version is None else next((v for v in history if v.version == version), None)
    if chosen is None or not chosen.snapshot:
        raise AppNotFound(app_id)
    return AppRecord(owner_id=owner_id, app_id=app_id, version=chosen.version, at=chosen.at, snapshot=chosen.snapshot)


def list_apps(owner_id: str) -> list[AppRecord]:
    out = []
    for app_id in cv.app_ids(owner_id):
        try:
            out.append(load_app(owner_id, app_id))
        except AppNotFound:
            continue
    return out


async def status(repo, app: AppRecord) -> str:
    if await repo.active_grant(owner_id=app.owner_id, app_id=app.app_id, manifest_hash=app.manifest_hash):
        return "approved"
    grants = await repo.grants(owner_id=app.owner_id, app_id=app.app_id)
    if grants and all(g["revoked_at"] is not None for g in grants):
        return "revoked"
    return "needs_approval"


def source_words(spec: dict) -> dict:
    entry = get_entry(spec["use"])
    if entry is None:  # a catalog entry removed since registration: refused at run time
        return {"words": "A source the platform no longer offers (it will not be read)", "link_hosts": []}
    return {"words": entry.words(spec["params"], spec["fields"]), "link_hosts": list(entry.link_hosts)}


async def source_views(repo, app: AppRecord) -> list[dict]:
    rows = {r["source"]: r for r in await repo.cache_rows(owner_id=app.owner_id, app_id=app.app_id) if r["manifest_hash"] == app.manifest_hash}
    out = []
    for name, spec in app.sources.items():
        row = rows.get(name) or {}
        out.append(
            {
                "name": name,
                "use": spec["use"],
                **source_words(spec),
                "fields": list(spec["fields"]),
                "params": dict(spec["params"]),
                "refresh_s": spec["refresh_s"],
                "refresh_words": refresh_words(spec["refresh_s"]),
                "last_fetched_at": iso(row.get("fetched_at")),
                "last_state": row.get("state"),
                "last_error": row.get("reason") if row.get("state") == "failed" else None,
            }
        )
    return out


def card_view(card: dict, app: AppRecord | None) -> dict:
    """An approval card. Words come from the version the card was drawn for."""
    sources: list[dict] = []
    name = ""
    if app is not None:
        try:
            drawn = load_app(app.owner_id, app.app_id, card["version"])
        except AppNotFound:
            drawn = app
        name = drawn.manifest["name"]
        sources = [{"name": n, "words": source_words(s)["words"], "refresh_words": refresh_words(s["refresh_s"])} for n, s in drawn.sources.items()]
    return {
        "id": card["id"],
        "app_id": card["app_id"],
        "app_name": name,
        "version": card["version"],
        "manifest_hash": card["manifest_hash"],
        "status": card["status"],
        "sources": sources,
        "sentence": DATA_SENTENCE,
        "suggestion": bool(card["suggestion"]),
        "suggestion_source": card.get("suggestion_source"),
        "thread_id": card.get("thread_id"),
        "created_at": iso(card["created_at"]),
        "resolved_at": iso(card.get("resolved_at")),
    }


async def summary(repo, app: AppRecord, pins: list[str]) -> dict[str, Any]:
    return {
        "id": app.app_id,
        "name": app.manifest["name"],
        "description": app.manifest.get("description", ""),
        "current_version": app.version,
        "manifest_hash": app.manifest_hash,
        "status": await status(repo, app),
        "pinned": app.app_id in pins,
        "updated_at": app.at,
        "last_opened_at": iso(await repo.opened_at(owner_id=app.owner_id, app_id=app.app_id)),
    }


async def detail(repo, app: AppRecord, pins: list[str]) -> dict[str, Any]:
    card = await repo.pending_card(owner_id=app.owner_id, app_id=app.app_id)
    return {**await summary(repo, app, pins), "html_url": app.html_url, "sources": await source_views(repo, app), "approval": card_view(card, app) if card else None}


async def raise_card_if_needed(repo, app: AppRecord, *, thread_id: str | None, suggestion: bool, suggestion_source: str | None) -> dict | None:
    """A new App access card when the version's hash has no active grant."""
    if await repo.active_grant(owner_id=app.owner_id, app_id=app.app_id, manifest_hash=app.manifest_hash):
        return None
    return await repo.create_card(owner_id=app.owner_id, app_id=app.app_id, version=app.version, manifest_hash=app.manifest_hash, thread_id=thread_id, suggestion=suggestion, suggestion_source=suggestion_source)
