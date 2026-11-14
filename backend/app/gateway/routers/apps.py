"""/api/apps: the Apps platform (Spec 011, Slice 1). Contract: specs/011-apps/api.md.

Every route needs the OWNER'S BROWSER SESSION. The internal token (channels,
the trigger engine, anything acting for the system) is refused on every route,
reads included: an agent can neither press the approval button nor read an
app's data. Another account's apps are 404.

The bridge (`/data`) serves only sources of the app's current version whose
manifest hash has an active grant, each through its catalog entry. Its results
go to the HTTP response and the apps cache only, never into a thread, a run,
memory or a model, and no bridge path writes anything else. Bridge calls are
not tool calls and mark no turn as a private read.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.apps import bridge, bundle, catalog, service
from app.gateway.apps.manifest import SOURCE_NAME
from app.gateway.apps.service import AppNotFound, AppRecord, load_app
from app.gateway.authz import require_permission
from app.gateway.internal_auth import INTERNAL_AUTH_HEADER_NAME, is_valid_internal_auth_token
from omniharness.config import config_versions as cv
from omniharness.runtime.user_context import DEFAULT_USER_ID

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/apps", tags=["apps"])


def _error(status: int, code: str, message: str, headers: dict | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message}, headers=headers)


def owner_of(request: Request) -> str:
    """The signed-in person, or 403 for anything acting for the system."""
    if is_valid_internal_auth_token(request.headers.get(INTERNAL_AUTH_HEADER_NAME)):
        raise _error(403, "owner_session_required", "Apps answer only the owner's own browser session.")
    auth = getattr(request.state, "auth", None)
    user = getattr(auth, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if str(user.id) == DEFAULT_USER_ID:
        raise _error(403, "owner_session_required", "Apps answer only the owner's own browser session.")
    return str(user.id)


def repo_of(request: Request):
    repo = getattr(request.app.state, "app_repo", None)
    if repo is None:
        raise _error(503, "apps_unavailable", "Apps need the gateway's SQL store.")
    return repo


async def _load_or_404(repo, owner_id: str, app_id: str, version: int | None = None) -> AppRecord:
    """Version `version`, or the version the app serves (the newest one not
    waiting on the owner's button). 404 with a code otherwise."""
    try:
        return load_app(owner_id, app_id, version) if version is not None else await service.served(repo, owner_id, app_id)
    except AppNotFound:
        pass
    if version is not None:
        try:
            load_app(owner_id, app_id)
        except AppNotFound:
            raise _error(404, "app_not_found", "No such app.") from None
        raise _error(404, "version_not_found", f"This app has no version {version}.")
    raise _error(404, "app_not_found", "No such app.")


# -- catalog and cards (before /{app_id}) --------------------------------------------


@router.get("/catalog")
@require_permission("threads", "read")
async def get_catalog(request: Request) -> dict:
    owner_of(request)
    return catalog.describe_catalog()


@router.get("/approvals")
@require_permission("threads", "read")
async def approvals_for_thread(request: Request, thread_id: str = Query(..., min_length=1, max_length=128)) -> dict:
    owner = owner_of(request)
    repo = repo_of(request)
    cards = []
    for card in await repo.cards_for_thread(owner_id=owner, thread_id=thread_id):
        try:
            app = await service.served(repo, owner, card["app_id"])
        except AppNotFound:
            app = None
        cards.append(service.card_view(card, app))
    return {"cards": cards}


# -- library ------------------------------------------------------------------------------


@router.get("")
@require_permission("threads", "read")
async def list_apps(request: Request) -> dict:
    owner = owner_of(request)
    repo = repo_of(request)
    pins = await repo.get_pins(user_id=owner)
    return {"apps": [await service.summary(repo, app, pins) for app in await service.list_apps(repo, owner)]}


@router.get("/{app_id}")
@require_permission("threads", "read")
async def get_app(app_id: str, request: Request) -> dict:
    owner = owner_of(request)
    repo = repo_of(request)
    return await service.detail(repo, await _load_or_404(repo, owner, app_id), await repo.get_pins(user_id=owner))


@router.get("/{app_id}/versions")
@require_permission("threads", "read")
async def get_versions(app_id: str, request: Request) -> dict:
    owner = owner_of(request)
    repo = repo_of(request)
    await _load_or_404(repo, owner, app_id)
    restored = cv.app_restored_from(owner, app_id)
    out = []
    for v in reversed(cv.app_history(owner, app_id)):
        digest = (v.snapshot or {}).get("manifest_hash")
        approved = bool(digest and await repo.active_grant(owner_id=owner, app_id=app_id, manifest_hash=digest))
        out.append({"version": v.version, "at": v.at, "who": v.who, "source": v.source, "changed": v.changed, "manifest_hash": digest, "approved": approved, "restored_from": restored.get(v.version)})
    return {"current": out[0]["version"] if out else 0, "versions": out}


class RestoreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_version: int = Field(ge=1)
    base_version: int | None = Field(default=None, ge=1)


@router.post("/{app_id}/restore")
@require_permission("threads", "write")
async def restore(app_id: str, body: RestoreIn, request: Request) -> dict:
    owner = owner_of(request)
    repo = repo_of(request)
    await _load_or_404(repo, owner, app_id)
    try:
        cv.restore_app(owner, app_id, body.to_version, who=owner, base_version=body.base_version)
    except cv.StaleWriteError as exc:
        raise _error(409, "stale_version", str(exc)) from exc
    except cv.VersionNotFoundError as exc:
        raise _error(404, "version_not_found", str(exc)) from exc
    app = await _load_or_404(repo, owner, app_id)
    await service.raise_card_if_needed(repo, app, thread_id=None, suggestion=False, suggestion_source=None)
    await repo.audit(owner_id=owner, app_id=app_id, event="app_restored", detail={"version": app.version, "restored_from": body.to_version, "manifest_hash": app.manifest_hash})
    return await service.detail(repo, app, await repo.get_pins(user_id=owner))


@router.get("/{app_id}/permissions")
@require_permission("threads", "read")
async def permissions(app_id: str, request: Request) -> dict:
    owner = owner_of(request)
    repo = repo_of(request)
    app = await _load_or_404(repo, owner, app_id)
    grants = [{"manifest_hash": g["manifest_hash"], "approved_at": service.iso(g["approved_at"]), "revoked_at": service.iso(g["revoked_at"]), "version": g["version"]} for g in await repo.grants(owner_id=owner, app_id=app_id)]
    return {
        "app_id": app_id,
        "version": app.version,
        "manifest_hash": app.manifest_hash,
        "status": await service.status(repo, app),
        "sentence": catalog.DATA_SENTENCE,
        "sources": await service.source_views(repo, app),
        "grants": grants,
        # The apps audit log for this app (approvals, revokes, refusals): events
        # and ids only, never data.
        "activity": [{"at": service.iso(e["at"]), "event": e["event"], "detail": e["detail"]} for e in await repo.audit_entries(owner_id=owner, app_id=app_id, limit=20)],
    }


@router.post("/{app_id}/revoke")
@require_permission("threads", "write")
async def revoke(app_id: str, request: Request) -> dict:
    owner = owner_of(request)
    repo = repo_of(request)
    app = await _load_or_404(repo, owner, app_id)
    ended = await repo.revoke_all(owner_id=owner, app_id=app_id)
    deleted = await repo.delete_cache(owner_id=owner, app_id=app_id)
    if ended:
        # The app shows an Approve again card in place of its tiles.
        await service.raise_card_if_needed(repo, app, thread_id=None, suggestion=False, suggestion_source=None)
    await repo.audit(owner_id=owner, app_id=app_id, event="app_revoked", detail={"grants_ended": ended, "cache_rows_deleted": deleted})
    return {"status": "revoked", "grants_ended": ended, "cache_rows_deleted": deleted}


# -- approval (button only) ------------------------------------------------------------


@router.get("/{app_id}/approval")
@require_permission("threads", "read")
async def get_approval(app_id: str, request: Request) -> dict:
    owner = owner_of(request)
    repo = repo_of(request)
    app = await _load_or_404(repo, owner, app_id)
    card = await repo.pending_card(owner_id=owner, app_id=app_id)
    if card is None:
        raise _error(404, "no_pending_approval", "This app has no approval waiting.")
    return service.card_view(card, app)


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    card_id: str = Field(pattern=r"^[0-9a-f]{32}$")


@router.post("/{app_id}/approve")
@require_permission("threads", "write")
async def approve(app_id: str, body: ApproveIn, request: Request) -> dict:
    """The App access card's Allow button. The only way a grant is made."""
    owner = owner_of(request)
    repo = repo_of(request)
    await _load_or_404(repo, owner, app_id)
    card = await repo.pending_card(owner_id=owner, app_id=app_id)
    if card is None or card["id"] != body.card_id:
        raise _error(404, "no_pending_approval", "This card is no longer waiting; reload it.")
    # The card is bound to the version it was drawn for (an immutable
    # snapshot); a newer registration supersedes it.
    drawn = await _load_or_404(repo, owner, app_id, card["version"])
    if body.manifest_hash != card["manifest_hash"] or drawn.manifest_hash != card["manifest_hash"]:
        raise _error(409, "hash_mismatch", "The app changed after this card was drawn; reload the card and check it again.")
    if not await repo.resolve_card(card_id=card["id"], owner_id=owner, status="approved"):
        raise _error(404, "no_pending_approval", "This card is no longer waiting; reload it.")
    grant = await repo.create_grant(owner_id=owner, app_id=app_id, manifest_hash=drawn.manifest_hash, version=drawn.version, card_id=card["id"])
    app = drawn
    await repo.audit(owner_id=owner, app_id=app_id, event="app_approved", detail={"version": app.version, "manifest_hash": app.manifest_hash, "card": card["id"], "via": "button"})
    return {"status": "approved", "manifest_hash": app.manifest_hash, "approved_at": service.iso(grant["approved_at"])}


class KeepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_id: str = Field(pattern=r"^[0-9a-f]{32}$")


@router.post("/{app_id}/keep")
@require_permission("threads", "write")
async def keep(app_id: str, body: KeepIn, request: Request) -> dict:
    """A version card's "Keep version M" button: the offered version is not
    served; the served one keeps running. Owner's button only, like approve."""
    owner = owner_of(request)
    repo = repo_of(request)
    await _load_or_404(repo, owner, app_id)
    card = await repo.pending_card(owner_id=owner, app_id=app_id)
    if card is None or card["id"] != body.card_id or not await repo.resolve_card(card_id=card["id"], owner_id=owner, status="kept"):
        raise _error(404, "no_pending_approval", "This card is no longer waiting; reload it.")
    await repo.audit(owner_id=owner, app_id=app_id, event="app_version_kept", detail={"version": card["version"], "card": card["id"], "via": "button"})
    return {"status": "kept", "version": card["version"]}


# -- bridge -----------------------------------------------------------------------------


@contextmanager
def _quiet_errors(app_id: str):
    """A bridge failure is logged by type and answered with a fixed message:
    an error's text or traceback (a database error with its statement, an
    upstream error) can carry the data the bridge was handling."""
    try:
        yield
    except (HTTPException, bridge.SourceRefused):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("app %s: the bridge failed (%s)", app_id, type(exc).__name__)
        raise _error(500, "bridge_failed", "The app's data could not be served.") from None


async def _bridge_gate(request: Request, app_id: str) -> tuple[Any, AppRecord]:
    owner = owner_of(request)
    repo = repo_of(request)
    app = await _load_or_404(repo, owner, app_id)
    if await repo.hit(owner_id=owner, app_id=app_id) > bridge.REQUESTS_PER_MINUTE:
        raise _error(429, "rate_limited", f"At most {bridge.REQUESTS_PER_MINUTE} requests per app per minute.", headers={"Retry-After": "60"})
    if not await repo.active_grant(owner_id=owner, app_id=app_id, manifest_hash=app.manifest_hash):
        await repo.audit(owner_id=owner, app_id=app_id, event="bridge_refused", detail={"reason": "not_approved", "manifest_hash": app.manifest_hash})
        raise _error(403, "not_approved", "This app's data sources have not been approved.")
    return repo, app


@router.get("/{app_id}/data")
@require_permission("threads", "read")
async def data_all(app_id: str, request: Request) -> dict:
    repo, app = await _bridge_gate(request, app_id)
    with _quiet_errors(app_id):
        await repo.mark_opened(owner_id=app.owner_id, app_id=app_id)
        return {"app_id": app_id, "version": app.version, "results": await bridge.serve_all(request.app.state, repo, app)}


@router.get("/{app_id}/data/{source}")
@require_permission("threads", "read")
async def data_one(app_id: str, source: str, request: Request, refresh: bool = Query(default=False)) -> dict:
    repo, app = await _bridge_gate(request, app_id)
    if source not in app.sources:
        await repo.audit(owner_id=app.owner_id, app_id=app_id, event="bridge_refused", detail={"reason": "unknown_source", "source": source if SOURCE_NAME.match(source) else "invalid"})
        raise _error(404, "unknown_source", "That source is not in this app's approved manifest.")
    try:
        with _quiet_errors(app_id):
            return await bridge.serve(request.app.state, repo, app, source, force=refresh)
    except bridge.SourceRefused as exc:
        await repo.audit(owner_id=app.owner_id, app_id=app_id, event="bridge_refused", detail={"reason": "source_refused", "source": source, "why": str(exc)[:200]})
        raise _error(403, "source_refused", f"This source is refused: {exc}") from exc


# -- the app document ------------------------------------------------------------------


@router.get("/{app_id}/versions/{version}/app.html")
@require_permission("threads", "read")
async def app_html(app_id: str, version: int, request: Request) -> Response:
    owner = owner_of(request)
    repo = repo_of(request)
    app = await _load_or_404(repo, owner, app_id, version)
    try:
        html = cv.read_app_bundle(owner, app.snapshot["bundle_hash"])
    except cv.VersionNotFoundError as exc:
        raise _error(404, "version_not_found", "This version's document is not available.") from exc
    await repo.mark_opened(owner_id=owner, app_id=app_id)
    headers = {**bundle.STATIC_HEADERS, "Content-Security-Policy": bundle.csp(list(app.snapshot.get("script_hashes") or []))}
    return Response(content=html, media_type="text/html; charset=utf-8", headers=headers)


@router.get("/{app_id}/versions/{version}/shots/{theme}.png")
@require_permission("threads", "read")
async def version_shot(app_id: str, version: int, theme: str, request: Request) -> Response:
    """One of the system's own check screenshots of a version (sample data,
    1280 px), stored with the version at registration. Owner only, PNG only."""
    if theme not in ("light", "dark"):
        raise _error(404, "version_not_found", "No such screenshot.")
    owner = owner_of(request)
    repo = repo_of(request)
    app = await _load_or_404(repo, owner, app_id, version)
    digest = (app.snapshot.get("shots") or {}).get(theme)
    try:
        png = cv.read_app_shot(owner, digest)
    except cv.VersionNotFoundError as exc:
        raise _error(404, "version_not_found", "No such screenshot.") from exc
    headers = {
        "Cache-Control": "private, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Content-Disposition": "inline",
    }
    return Response(content=png, media_type="image/png", headers=headers)


class RefusedIn(BaseModel):
    """Codes only, no free text: a frame's message cannot carry data into the
    audit log through a refusal report (the host sends the code, the message
    type, and the source name the frame asked for when it is a valid name)."""

    model_config = ConfigDict(extra="forbid")
    reason: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    type: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,31}$")
    source: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,31}$")


@router.post("/{app_id}/refused", status_code=204)
@require_permission("threads", "write")
async def message_refused(app_id: str, body: RefusedIn, request: Request) -> Response:
    """The host page reports a frame message it dropped (FR-022)."""
    owner = owner_of(request)
    repo = repo_of(request)
    await _load_or_404(repo, owner, app_id)
    if await repo.hit(owner_id=owner, app_id=app_id) > bridge.REQUESTS_PER_MINUTE:
        raise _error(429, "rate_limited", f"At most {bridge.REQUESTS_PER_MINUTE} requests per app per minute.", headers={"Retry-After": "60"})
    await repo.audit(owner_id=owner, app_id=app_id, event="app_message_refused", detail=body.model_dump())
    return Response(status_code=204)
