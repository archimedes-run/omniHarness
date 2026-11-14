"""/api/artifacts: the Artifact store (Spec 012, Slice 1). Contract: specs/012-artifacts/api.md.

Every route needs the OWNER'S BROWSER SESSION. The internal token (channels,
the trigger engine, anything acting for the system) is refused on every route,
reads included. Another account's artifact is 404, exactly as an id that does
not exist. No route takes a filesystem path: ids are matched against a fixed
pattern and looked up in the SQL store; content is read by its hash.

Content is served so that nothing in it can run on this origin: every
response carries nosniff, `Content-Security-Policy: default-src 'none';
sandbox` and `Cross-Origin-Resource-Policy: same-origin`; SVG is served as an
image (render it only through `<img>`), text as text/plain, a `file` as an
attachment.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from typing import Any, Literal

import jwt
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.artifacts_store import caps, code_service, frame, kinds
from app.gateway.artifacts_store.kinds import InvalidContent, TooLarge
from app.gateway.artifacts_store.service import run_import
from app.gateway.artifacts_store.store import ArtifactStore, NotEditable, StoreError
from app.gateway.auth.config import get_auth_config
from app.gateway.authz import require_permission
from app.gateway.internal_auth import INTERNAL_AUTH_HEADER_NAME, is_valid_internal_auth_token
from omniharness.runtime.user_context import DEFAULT_USER_ID

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/artifacts", tags=["artifact-store"])

_ID = re.compile(r"^[A-Za-z0-9_-]{22}$")
_THREAD = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
CONTENT_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Cross-Origin-Resource-Policy": "same-origin",
    # Not cached: a deleted artifact's content must not linger in a cache.
    "Cache-Control": "private, no-store",
}


def _error(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def owner_of(request: Request) -> str:
    """The signed-in person, or 403 for anything acting for the system."""
    if is_valid_internal_auth_token(request.headers.get(INTERNAL_AUTH_HEADER_NAME)):
        raise _error(403, "owner_session_required", "The Artifact store answers only the owner's own browser session.")
    user = getattr(getattr(request.state, "auth", None), "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if str(user.id) == DEFAULT_USER_ID:
        raise _error(403, "owner_session_required", "The Artifact store answers only the owner's own browser session.")
    return str(user.id)


def store_of(request: Request) -> ArtifactStore:
    store = getattr(request.app.state, "artifact_store", None)
    if store is None:
        raise _error(503, "artifacts_unavailable", "Artifacts need the gateway's SQL store.")
    return store


def _check_id(artifact_id: str) -> str:
    if not _ID.fullmatch(artifact_id or ""):
        raise _error(404, "artifact_not_found", "No such artifact.")
    return artifact_id


async def _call(fn, *args, **kwargs):
    """Run a store call in the threadpool; its errors become coded HTTP errors."""
    try:
        return await run_in_threadpool(fn, *args, **kwargs)
    except StoreError as exc:
        raise _error(exc.status, exc.code, exc.message, **exc.extra) from None
    except TooLarge as exc:
        raise _error(413, "too_large", "The content is over its cap.", size=exc.size, cap=exc.cap) from None
    except InvalidContent as exc:
        raise _error(422, "invalid_content", "The content does not fit its kind.", reason=str(exc)) from None


def _schedule_import(background: BackgroundTasks, store: ArtifactStore, owner: str, thread_id: str | None = None) -> None:
    background.add_task(run_in_threadpool, run_import, store, owner, thread_id=thread_id)


# -- reads ---------------------------------------------------------------------------------


@router.get("")
@require_permission("threads", "read")
async def list_artifacts(
    request: Request,
    background: BackgroundTasks,
    kind: Literal["markdown", "code", "svg", "mermaid", "chart", "image", "file", "html", "react"] | None = None,
    pinned: bool | None = None,
    archived: Literal["false", "true", "all"] = "false",
    thread: str | None = Query(None, max_length=128),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
) -> dict:
    owner = owner_of(request)
    store = store_of(request)
    rows, total = await _call(store.list, owner, kind=kind, pinned=pinned, archived=archived, thread=thread, q=q or None, limit=limit, offset=offset)
    used = await _call(store.usage, owner)
    _schedule_import(background, store, owner)
    return {"artifacts": rows, "total": total, "usage": {"used": used, "cap": caps.OWNER_BYTES}}


@router.get("/usage")
@require_permission("threads", "read")
async def usage(request: Request) -> dict:
    owner = owner_of(request)
    return {"used": await _call(store_of(request).usage, owner), "cap": caps.OWNER_BYTES}


@router.get("/threads/{thread_id}")
@require_permission("threads", "read")
async def thread_artifacts(thread_id: str, request: Request, background: BackgroundTasks) -> dict:
    owner = owner_of(request)
    store = store_of(request)
    if not _THREAD.fullmatch(thread_id):
        return {"artifacts": []}
    rows = await _call(store.thread_artifacts, owner, thread_id)
    _schedule_import(background, store, owner, thread_id)
    return {"artifacts": rows}


@router.get("/{artifact_id}")
@require_permission("threads", "read")
async def get_artifact(artifact_id: str, request: Request) -> dict:
    owner = owner_of(request)
    return await _call(store_of(request).detail, owner, _check_id(artifact_id))


@router.get("/{artifact_id}/versions")
@require_permission("threads", "read")
async def list_versions(artifact_id: str, request: Request) -> dict:
    owner = owner_of(request)
    return {"versions": await _call(store_of(request).versions, owner, _check_id(artifact_id))}


@router.get("/{artifact_id}/versions/{n}")
@require_permission("threads", "read")
async def get_version(artifact_id: str, n: int, request: Request) -> dict:
    owner = owner_of(request)
    store = store_of(request)
    summary, meta, row = await _call(store.version, owner, _check_id(artifact_id), n)
    content = None
    if summary["kind"] in ("markdown", "mermaid", "code", "chart", "html") and row.stored == "blob":
        content = kinds.content_for_api(summary["kind"], await _call(store.content, owner, row))
    out = {**meta, "content": content}
    if summary["kind"] in kinds.CODE_KINDS and row.stored == "blob":
        _, _, code, _ = await _call(store.code_version, owner, artifact_id, n)
        if summary["kind"] == "react":
            src = await _call(store.source, owner, code)
            out["source"] = json.loads(src) if src else None
        out["build_log"] = code.build_log
    return out


@router.get("/{artifact_id}/versions/{n}/content")
@require_permission("threads", "read")
async def get_content(artifact_id: str, n: int, request: Request) -> Response:
    owner = owner_of(request)
    store = store_of(request)
    summary, meta, row = await _call(store.version, owner, _check_id(artifact_id), n)
    if row.stored != "blob":
        raise _error(409, "lives_in_chat", "This file is too large for the store and lives in its chat.", thread_id=row.thread_id, path=f"/mnt/user-data/outputs/{row.chat_path}")
    data = await _call(store.content, owner, row)
    kind = summary["kind"]
    headers = {**CONTENT_HEADERS, "ETag": f'"{row.content_hash}"'}
    if kind in ("markdown", "mermaid"):
        return Response(data, media_type="text/plain; charset=utf-8", headers=headers)
    if kind == "code":
        code = kinds.content_for_api("code", data)
        headers["X-Artifact-Language"] = str(code.get("language") or "text")
        return Response(str(code.get("text", "")).encode("utf-8"), media_type="text/plain; charset=utf-8", headers=headers)
    if kind == "chart":
        return Response(data, media_type="application/json", headers=headers)
    if kind in kinds.CODE_KINDS:
        # Source as TEXT, never as a page: code runs only in the frame route.
        headers["Content-Disposition"] = "inline"
        return Response(data, media_type="text/plain; charset=utf-8", headers=headers)
    if kind == "svg":
        return Response(data, media_type="image/svg+xml", headers=headers)
    if kind == "image" and meta["media_type"] in kinds.IMAGE_TYPES:
        return Response(data, media_type=meta["media_type"], headers=headers)
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", summary["title"])[:100] or "artifact"
    headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(data, media_type="application/octet-stream", headers=headers)


# -- writes (CSRF by the middleware) ----------------------------------------------------


class PatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(None, max_length=400)
    pinned: bool | None = None


class EditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: int = Field(..., ge=1)
    content: str = Field(..., max_length=caps.TEXT_VERSION_BYTES)
    language: str | None = Field(None, max_length=32)


class RestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(..., ge=1)
    base_version: int = Field(..., ge=1)


class DuplicateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int | None = Field(None, ge=1)
    title: str | None = Field(None, max_length=400)


class DeleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_id: str = Field(..., max_length=64)
    version_count: int = Field(..., ge=0)


@router.patch("/{artifact_id}")
@require_permission("threads", "write")
async def patch_artifact(artifact_id: str, body: PatchBody, request: Request) -> dict:
    owner = owner_of(request)
    if body.title is None and body.pinned is None:
        raise _error(422, "invalid_request", "Send a title, pinned, or both.")
    return await _call(store_of(request).patch, owner, _check_id(artifact_id), title=body.title, pinned=body.pinned)


@router.post("/{artifact_id}/archive")
@require_permission("threads", "write")
async def archive(artifact_id: str, request: Request) -> dict:
    owner = owner_of(request)
    return await _call(store_of(request).set_archived, owner, _check_id(artifact_id), True)


@router.post("/{artifact_id}/unarchive")
@require_permission("threads", "write")
async def unarchive(artifact_id: str, request: Request) -> dict:
    owner = owner_of(request)
    return await _call(store_of(request).set_archived, owner, _check_id(artifact_id), False)


@router.post("/{artifact_id}/versions", status_code=201)
@require_permission("threads", "write")
async def owner_edit(artifact_id: str, body: EditBody, request: Request, background: BackgroundTasks) -> dict:
    owner = owner_of(request)
    store = store_of(request)
    artifact_id = _check_id(artifact_id)

    def build(s, row):
        if row.kind not in kinds.OWNER_EDIT_KINDS:
            raise NotEditable("Only markdown, code, mermaid and html artifacts are edited here (react: Rebuild).")
        if row.kind == "html":
            canon, findings = frame.canonical_html(body.content)
            return kinds.Canonical(canon.data, canon.media_type, None, body.content), {"build_state": "ok", "findings": findings, "recipe": {"tool": "none", "kind": "html"}}
        language = body.language
        if row.kind == "code" and language is None:
            language = kinds.content_for_api("code", store.latest_bytes(s, row)).get("language")
        return kinds.canonical(row.kind, body.content, language=language)

    summary, version = await _call(store.add_version, owner, artifact_id, base_version=body.base_version, build=build, lineage="user", lineage_source=None, origin="owner_edit")
    _schedule_check(background, store, owner, summary, version)
    return {"artifact": summary, "version": version}


@router.post("/{artifact_id}/restore", status_code=201)
@require_permission("threads", "write")
async def restore(artifact_id: str, body: RestoreBody, request: Request, background: BackgroundTasks) -> dict:
    owner = owner_of(request)
    store = store_of(request)
    summary, version = await _call(store.restore, owner, _check_id(artifact_id), version=body.version, base_version=body.base_version)
    _schedule_check(background, store, owner, summary, version)
    return {"artifact": summary, "version": version}


@router.post("/{artifact_id}/duplicate", status_code=201)
@require_permission("threads", "write")
async def duplicate(artifact_id: str, body: DuplicateBody, request: Request) -> dict:
    owner = owner_of(request)
    return await _call(store_of(request).duplicate, owner, _check_id(artifact_id), version=body.version, title=body.title)


@router.post("/{artifact_id}/delete")
@require_permission("threads", "write")
async def delete_artifact(artifact_id: str, body: DeleteBody, request: Request) -> dict:
    owner = owner_of(request)
    await _call(store_of(request).delete, owner, _check_id(artifact_id), confirm_id=body.confirm_id, version_count=body.version_count)
    return {"deleted": artifact_id}


# -- code kinds: the locked frame, checks, rebuild (Slice 2) ------------------------------

FRAME_TOKEN_TYPE = "artifact_frame"
#: A view's token lives this long; a frame (re)loaded later asks for a new one.
FRAME_TOKEN_SECONDS = 300
#: Served instead of the artifact to anything but this app's own frame request.
INERT_PAGE = b'<!doctype html><html><head><meta charset="utf-8"><title>Artifact</title></head><body style="font:14px system-ui,sans-serif;margin:2rem">Open this artifact in OmniHarness.</body></html>'
INERT_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cache-Control": "private, no-store",
}


def _schedule_check(background: BackgroundTasks, store: ArtifactStore, owner: str, summary: dict, version: dict) -> None:
    """A new code version made by the owner: its checks run after the
    response, in the sandbox of the chat that made the artifact."""
    if summary.get("kind") not in kinds.CODE_KINDS:
        return
    code = version.get("code") or {}
    if code.get("build_state") != "ok" or (code.get("check") or {}).get("state") != "pending":
        return
    background.add_task(run_in_threadpool, code_service.check_version, store, owner, summary["id"], version["n"], summary.get("origin_thread_id"))


def _frame_token(owner: str, artifact_id: str, n: int) -> str:
    now = int(time.time())
    payload = {"typ": FRAME_TOKEN_TYPE, "sub": owner, "aid": artifact_id, "n": n, "iat": now, "exp": now + FRAME_TOKEN_SECONDS, "jti": secrets.token_urlsafe(12)}
    return jwt.encode(payload, get_auth_config().jwt_secret, algorithm="HS256")


def _token_ok(token: str | None, owner: str, artifact_id: str, n: int) -> bool:
    if not token or len(token) > 1024:
        return False
    try:
        payload = jwt.decode(token, get_auth_config().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return False
    return payload.get("typ") == FRAME_TOKEN_TYPE and payload.get("sub") == owner and payload.get("aid") == artifact_id and payload.get("n") == n


def _inert(status: int = 403) -> Response:
    return Response(INERT_PAGE, status_code=status, media_type="text/html; charset=utf-8", headers=INERT_HEADERS)


@router.get("/{artifact_id}/versions/{n}/frame-token")
@require_permission("threads", "read")
async def frame_token(artifact_id: str, n: int, request: Request) -> dict:
    """A short-lived token for ONE view of one version's frame (the host
    page asks for it right before it creates the iframe)."""
    owner = owner_of(request)
    store = store_of(request)
    artifact_id = _check_id(artifact_id)
    _, _, code, _ = await _call(store.code_version, owner, artifact_id, n)
    if code.build_state != "ok":
        raise _error(409, "build_failed", "This version did not build; it has no document to show.")
    token = _frame_token(owner, artifact_id, n)
    return {"token": token, "expires_in": FRAME_TOKEN_SECONDS, "url": f"/api/artifacts/{artifact_id}/versions/{n}/frame.html?t={token}"}


@router.get("/{artifact_id}/versions/{n}/frame.html")
@require_permission("threads", "read")
async def frame_html(artifact_id: str, n: int, request: Request, t: str | None = Query(None, max_length=1024)) -> Response:
    """The locked frame's document (FR-016, FR-031). Served ONLY to this
    app's own iframe request (Sec-Fetch-Dest: iframe, Sec-Fetch-Site:
    same-origin) carrying a valid view token for this owner and version;
    anything else (a top-level open, a link, a fetch, another site) gets an
    inert page. The document carries the CSP's sandbox directive too, so even
    if it were opened as a page it would run in an opaque origin."""
    owner = owner_of(request)
    store = store_of(request)
    artifact_id = _check_id(artifact_id)
    if request.headers.get("sec-fetch-dest") != "iframe" or request.headers.get("sec-fetch-site") != "same-origin" or not _token_ok(t, owner, artifact_id, n):
        return _inert()
    try:
        _, version, code, _ = await run_in_threadpool(store.code_version, owner, artifact_id, n)
    except StoreError:
        return _inert(404)
    if code.build_state != "ok" or version.stored != "blob":
        return _inert(409)
    data = await run_in_threadpool(store.content, owner, version)
    document = frame.frame_document(data)
    return Response(document, media_type="text/html; charset=utf-8", headers={**frame.HEADERS, "Content-Security-Policy": frame.CSP})


@router.get("/{artifact_id}/versions/{n}/shots/{theme}.png")
@require_permission("threads", "read")
async def check_shot(artifact_id: str, n: int, theme: str, request: Request) -> Response:
    """The checks' own screenshot of a version at 1280 px (store previews)."""
    if theme not in ("light", "dark"):
        raise _error(404, "version_not_found", "No such screenshot.")
    owner = owner_of(request)
    png = await _call(store_of(request).shot, owner, _check_id(artifact_id), n, theme)
    if not png:
        raise _error(404, "version_not_found", "No such screenshot.")
    return Response(png, media_type="image/png", headers={**CONTENT_HEADERS, "Content-Disposition": "inline"})


@router.post("/{artifact_id}/versions/{n}/check", status_code=202)
@require_permission("threads", "write")
async def check_again(artifact_id: str, n: int, request: Request, background: BackgroundTasks) -> dict:
    """Run the checks again for a version they gave no answer for."""
    owner = owner_of(request)
    store = store_of(request)
    artifact_id = _check_id(artifact_id)
    summary, _, code, _ = await _call(store.code_version, owner, artifact_id, n)
    if code.build_state != "ok":
        raise _error(409, "build_failed", "This version did not build.")
    if not await _call(store.restart_check, owner, artifact_id, n):
        raise _error(409, "already_checked", "This version's checks already have an answer.")
    background.add_task(run_in_threadpool, code_service.check_version, store, owner, artifact_id, n, summary.get("origin_thread_id"))
    return {"state": "pending"}


class RebuildBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: int = Field(..., ge=1)
    content: dict[str, Any]


def _run_rebuild(store: ArtifactStore, owner: str, artifact_id: str, base_version: int, data: bytes, parsed: dict, thread_id: str | None) -> None:
    """Background: build, store the version (owner_edit, lineage user), check it."""
    try:
        built = code_service.build_react(owner, thread_id, parsed, beat=lambda: store.beat_build(owner, artifact_id))
        if built is None:
            store.end_build(owner, artifact_id, state="failed", reason="react artifacts are built in their chat's sandbox, which is not available here")
            return
        code = {"source": data, "recipe": built.recipe, "build_log": built.log, "findings": built.findings, "build_state": "ok" if built.ok else "build_failed"}
        canon = built.canon if built.ok else kinds.Canonical(data, "application/json")
        if not built.ok:
            code["build_log"] = (built.reason + "\n" + built.log).strip()
        summary, version = store.add_version(owner, artifact_id, base_version=base_version, canon=canon, code=code, lineage="user", lineage_source=None, origin="owner_edit", note="Rebuilt from edited source")
        store.end_build(owner, artifact_id, state="done" if built.ok else "failed", reason=None if built.ok else built.reason, result_version=version["n"])
        if built.ok:
            code_service.check_version(store, owner, artifact_id, version["n"], thread_id)
    except StoreError as exc:
        store.end_build(owner, artifact_id, state="failed", reason=exc.message)
    except Exception:  # noqa: BLE001 - recorded, never silent
        logger.exception("artifact rebuild failed")
        store.end_build(owner, artifact_id, state="failed", reason="the build could not run")


@router.post("/{artifact_id}/rebuild", status_code=202)
@require_permission("threads", "write")
async def rebuild(artifact_id: str, body: RebuildBody, request: Request, background: BackgroundTasks) -> dict:
    """The owner edited a react artifact's source: build it in the chat's
    sandbox (a build job, after the response); the version appears when it
    ends (`GET /{id}` shows `code.build` meanwhile)."""
    owner = owner_of(request)
    store = store_of(request)
    artifact_id = _check_id(artifact_id)
    try:
        data, parsed = frame.canonical_react_source(body.content)
    except (InvalidContent, TooLarge) as exc:
        await _call(_raise, exc)
    await _call(store.start_build, owner, artifact_id, body.base_version)
    summary = await _call(store.get, owner, artifact_id)
    background.add_task(run_in_threadpool, _run_rebuild, store, owner, artifact_id, body.base_version, data, parsed, summary.get("origin_thread_id"))
    return {"build": (summary.get("code") or {}).get("build")}


def _raise(exc: Exception) -> None:
    raise exc


class RefusedIn(BaseModel):
    """Codes only: a frame's message cannot carry text into the log."""

    model_config = ConfigDict(extra="forbid")
    reason: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    type: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,31}$")


@router.post("/{artifact_id}/refused", status_code=204)
@require_permission("threads", "write")
async def message_refused(artifact_id: str, body: RefusedIn, request: Request) -> Response:
    """FR-019: a frame message the host dropped, logged as artifact_message_refused."""
    owner_of(request)
    _check_id(artifact_id)
    logger.info("artifact_message_refused artifact=%s reason=%s type=%s", artifact_id, body.reason, body.type or "-")
    return Response(status_code=204)
