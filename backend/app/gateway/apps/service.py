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


def load_app(owner_id: str, app_id: str, version: int | None = None, *, skip: frozenset[int] | set[int] = frozenset()) -> AppRecord:
    """Version `version`, or else the newest version not in `skip`, or AppNotFound."""
    try:
        history = cv.app_history(owner_id, app_id)
    except ValueError as exc:  # an invalid id or user id
        raise AppNotFound(app_id) from exc
    if not history:
        raise AppNotFound(app_id)
    if version is None:
        chosen = ([v for v in history if v.version not in skip] or history)[-1]
    else:
        chosen = next((v for v in history if v.version == version), None)
    if chosen is None or not chosen.snapshot:
        raise AppNotFound(app_id)
    return AppRecord(owner_id=owner_id, app_id=app_id, version=chosen.version, at=chosen.at, snapshot=chosen.snapshot)


async def unserved_versions(repo, owner_id: str, app_id: str) -> set[int]:
    """Held versions (registered from content) the owner's button has not approved."""
    try:
        held = cv.app_held_versions(owner_id, app_id)
    except ValueError as exc:
        raise AppNotFound(app_id) from exc
    return held - await repo.granted_versions(owner_id=owner_id, app_id=app_id) if held else set()


async def served(repo, owner_id: str, app_id: str) -> AppRecord:
    """The version the app serves: the newest one not waiting on the owner's button."""
    return load_app(owner_id, app_id, skip=await unserved_versions(repo, owner_id, app_id))


async def pending_version(repo, app: AppRecord) -> int | None:
    """A newer version waiting on the owner's button, if any."""
    latest = load_app(app.owner_id, app.app_id)
    return latest.version if latest.version != app.version else None


async def list_apps(repo, owner_id: str) -> list[AppRecord]:
    out = []
    for app_id in cv.app_ids(owner_id):
        try:
            out.append(await served(repo, owner_id, app_id))
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


SUGGESTION_SOURCE_MAX = 120


def clean_source(text: object) -> str | None:
    """A suggestion's source label as plain, bounded text: no control or
    formatting characters, no quotes or angle brackets, whitespace collapsed,
    at most SUGGESTION_SOURCE_MAX characters. Shown quoted, as text."""
    if not text:
        return None
    import unicodedata

    kept = "".join(" " if unicodedata.category(ch)[0] in ("C", "Z") else ch for ch in str(text) if ch not in '<>"“”`')
    kept = " ".join(kept.split())[:SUGGESTION_SOURCE_MAX].strip()
    return kept or None


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
        "suggestion_source": clean_source(card.get("suggestion_source")),
        "suggestion_words": f"Suggested after reading: “{clean_source(card.get('suggestion_source'))}”" if card["suggestion"] else None,
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
        "pending_version": await pending_version(repo, app),
    }


async def detail(repo, app: AppRecord, pins: list[str]) -> dict[str, Any]:
    card = await repo.pending_card(owner_id=app.owner_id, app_id=app.app_id)
    return {**await summary(repo, app, pins), "html_url": app.html_url, "sources": await source_views(repo, app), "approval": card_view(card, app) if card else None}


async def raise_card_if_needed(repo, app: AppRecord, *, thread_id: str | None, suggestion: bool, suggestion_source: str | None, held: bool = False) -> dict | None:
    """A new App access card when the version's hash has no active grant, or
    when the version is held (registered from content: even a code-only
    change waits on the owner's button)."""
    if not held and await repo.active_grant(owner_id=app.owner_id, app_id=app.app_id, manifest_hash=app.manifest_hash):
        return None
    return await repo.create_card(owner_id=app.owner_id, app_id=app.app_id, version=app.version, manifest_hash=app.manifest_hash, thread_id=thread_id, suggestion=suggestion, suggestion_source=suggestion_source)
