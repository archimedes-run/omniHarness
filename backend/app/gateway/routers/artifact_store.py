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

import re
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.artifacts_store import caps, kinds
from app.gateway.artifacts_store.kinds import InvalidContent, TooLarge
from app.gateway.artifacts_store.service import run_import
from app.gateway.artifacts_store.store import ArtifactStore, NotEditable, StoreError
from app.gateway.authz import require_permission
from app.gateway.internal_auth import INTERNAL_AUTH_HEADER_NAME, is_valid_internal_auth_token
from omniharness.runtime.user_context import DEFAULT_USER_ID

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
    kind: Literal["markdown", "code", "svg", "mermaid", "chart", "image", "file"] | None = None,
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
    if summary["kind"] in ("markdown", "mermaid", "code", "chart") and row.stored == "blob":
        content = kinds.content_for_api(summary["kind"], await _call(store.content, owner, row))
    return {**meta, "content": content}


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
async def owner_edit(artifact_id: str, body: EditBody, request: Request) -> dict:
    owner = owner_of(request)
    store = store_of(request)
    artifact_id = _check_id(artifact_id)

    def build(s, row):
        if row.kind not in kinds.OWNER_EDIT_KINDS:
            raise NotEditable("Only markdown, code and mermaid artifacts are edited here.")
        language = body.language
        if row.kind == "code" and language is None:
            language = kinds.content_for_api("code", store.latest_bytes(s, row)).get("language")
        return kinds.canonical(row.kind, body.content, language=language)

    summary, version = await _call(store.add_version, owner, artifact_id, base_version=body.base_version, build=build, lineage="user", lineage_source=None, origin="owner_edit")
    return {"artifact": summary, "version": version}


@router.post("/{artifact_id}/restore", status_code=201)
@require_permission("threads", "write")
async def restore(artifact_id: str, body: RestoreBody, request: Request) -> dict:
    owner = owner_of(request)
    summary, version = await _call(store_of(request).restore, owner, _check_id(artifact_id), version=body.version, base_version=body.base_version)
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
