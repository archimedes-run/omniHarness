from __future__ import annotations

import logging
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.gateway import preview_frame
from app.gateway.authz import get_auth_context, require_permission
from app.gateway.deps import get_preview_session_manager
from app.gateway.preview_sessions import (
    PreviewFrameResponse,
    PreviewSessionCreateRequest,
    PreviewSessionLogsResponse,
    PreviewSessionResponse,
)
from app.gateway.routers.artifacts import get_artifact_manifest_for_preview
from omniharness.config.paths import get_paths
from omniharness.runtime.user_context import reset_current_user, set_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads", tags=["previews"])


def _current_user_id(request: Request) -> str:
    auth = get_auth_context(request)
    if auth is None:
        raise RuntimeError("Authenticated preview route missing auth context")
    return str(auth.require_user().id)


@router.post("/{thread_id}/previews", response_model=PreviewSessionResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def create_preview_session(
    thread_id: str,
    body: PreviewSessionCreateRequest,
    request: Request,
) -> PreviewSessionResponse:
    manager = get_preview_session_manager(request)
    return await manager.create_session(
        user_id=_current_user_id(request),
        thread_id=thread_id,
        body=body,
    )


@router.get("/{thread_id}/previews", response_model=list[PreviewSessionResponse])
@require_permission("threads", "read", owner_check=True)
async def list_preview_sessions(thread_id: str, request: Request) -> list[PreviewSessionResponse]:
    manager = get_preview_session_manager(request)
    return await manager.list_sessions(
        user_id=_current_user_id(request),
        thread_id=thread_id,
    )


@router.get("/{thread_id}/previews/{preview_id}", response_model=PreviewSessionResponse)
@require_permission("threads", "read", owner_check=True)
async def get_preview_session(thread_id: str, preview_id: str, request: Request) -> PreviewSessionResponse:
    manager = get_preview_session_manager(request)
    return await manager.get_session(
        user_id=_current_user_id(request),
        thread_id=thread_id,
        preview_id=preview_id,
    )


@router.get("/{thread_id}/previews/{preview_id}/logs", response_model=PreviewSessionLogsResponse)
@require_permission("threads", "read", owner_check=True)
async def get_preview_logs(thread_id: str, preview_id: str, request: Request) -> PreviewSessionLogsResponse:
    manager = get_preview_session_manager(request)
    return await manager.get_logs(
        user_id=_current_user_id(request),
        thread_id=thread_id,
        preview_id=preview_id,
    )


@router.post("/{thread_id}/previews/{preview_id}/stop", response_model=PreviewSessionResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def stop_preview_session(thread_id: str, preview_id: str, request: Request) -> PreviewSessionResponse:
    manager = get_preview_session_manager(request)
    return await manager.stop_session(
        user_id=_current_user_id(request),
        thread_id=thread_id,
        preview_id=preview_id,
    )


@router.post("/{thread_id}/previews/{preview_id}/restart", response_model=PreviewSessionResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def restart_preview_session(thread_id: str, preview_id: str, request: Request) -> PreviewSessionResponse:
    manager = get_preview_session_manager(request)
    return await manager.restart_session(
        user_id=_current_user_id(request),
        thread_id=thread_id,
        preview_id=preview_id,
    )


@router.post("/{thread_id}/previews/{preview_id}/frame", response_model=PreviewFrameResponse)
@require_permission("threads", "read", owner_check=True)
async def create_preview_frame_link(thread_id: str, preview_id: str, request: Request) -> PreviewFrameResponse:
    """A short-lived link for the live preview's sandboxed frame
    (preview_frame.py). The panel asks again before it lapses."""
    manager = get_preview_session_manager(request)
    return manager.frame_link(user_id=_current_user_id(request), thread_id=thread_id, preview_id=preview_id)


_FRAME_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


@router.api_route("/{thread_id}/previews/{preview_id}/live/{token}", methods=_FRAME_METHODS)
@router.api_route("/{thread_id}/previews/{preview_id}/live/{token}/{path:path}", methods=_FRAME_METHODS)
async def proxy_preview_frame(
    thread_id: str,
    preview_id: str,
    token: str,
    request: Request,
    path: str = "",
) -> Response:
    """The live preview, for its sandboxed frame. No session: the token in the
    path authorizes this one preview (auth_middleware lists the path as
    public, csrf_middleware exempts it), and every response carries the
    frame's sandbox. Navigations from the frame itself are cross-site by
    design (an opaque origin), so no Fetch Metadata refusal here."""
    try:
        manager = get_preview_session_manager(request)
        session = manager.frame_session(thread_id=thread_id, preview_id=preview_id, token=token)
        if session is None:
            return preview_frame.expired_response()
        # The owner's account, checked on every request: a token of an account
        # that is gone or no longer admitted opens nothing.
        if not await _owner_admitted(session.user_id):
            return preview_frame.error_response(404, "Preview not found", request)
        # The preview's owner, as the auth middleware would stamp it on a session
        # route: anything resolving the thread's data does so by this user.
        owner = set_current_user(SimpleNamespace(id=session.user_id))
        try:
            return await manager.proxy_request(session=session, token=token, request=request, path=path)
        finally:
            reset_current_user(owner)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Preview request failed"
        return preview_frame.error_response(exc.status_code, detail, request)
    except Exception:
        logger.exception("live preview request failed")
        return preview_frame.error_response(500, "Preview request failed", request)


async def _owner_admitted(user_id: str) -> bool:
    from app.gateway.deps import get_local_provider
    from app.gateway.ownership import account_admitted

    try:
        user = await get_local_provider().get_user(user_id)
    except Exception:
        return False
    return await account_admitted(user)


@router.post("/{thread_id}/artifacts/manifests/{artifact_id}/preview", response_model=PreviewSessionResponse)
@require_permission("threads", "write", owner_check=True)
async def create_preview_from_manifest(
    thread_id: str,
    artifact_id: str,
    request: Request,
) -> PreviewSessionResponse:
    """Create or reuse a preview session from a server-validated web_app manifest.

    The browser does not need to supply command, root_path, or port — all values
    come from the manifest file on disk, which is validated server-side.
    """
    user_id = _current_user_id(request)
    manifest = get_artifact_manifest_for_preview(thread_id, artifact_id, user_id=user_id)
    if manifest.type != "web_app":
        raise HTTPException(
            status_code=422,
            detail=f"Manifest type '{manifest.type}' does not support live preview; only web_app manifests do",
        )
    # Use source_path (where agent put the code) when the directory exists.
    # Fall back to root_path (manifest's physical location in outputs) when
    # source_path was wrongly inferred as workspace but the code is actually in outputs.
    effective_root = manifest.root_path
    if manifest.source_path:
        try:
            resolved = get_paths().resolve_virtual_path(thread_id, manifest.source_path, user_id=user_id)
            if resolved.is_dir():
                effective_root = manifest.source_path
        except Exception:
            pass

    body = PreviewSessionCreateRequest(
        artifact_id=manifest.id,
        root_path=effective_root,
        command=manifest.preview.command,  # guaranteed non-None for dev_server by manifest validator
        port=manifest.preview.port,
    )
    manager = get_preview_session_manager(request)
    return await manager.create_session_from_manifest(
        user_id=user_id,
        thread_id=thread_id,
        body=body,
    )
