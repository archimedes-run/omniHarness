from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.gateway.authz import get_auth_context, require_permission
from app.gateway.deps import get_preview_session_manager
from app.gateway.preview_sessions import (
    PreviewSessionCreateRequest,
    PreviewSessionLogsResponse,
    PreviewSessionResponse,
)
from app.gateway.routers.artifacts import get_artifact_manifest_for_preview

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


@router.api_route(
    "/{thread_id}/previews/{preview_id}/proxy",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
@router.api_route(
    "/{thread_id}/previews/{preview_id}/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
@require_permission("threads", "read", owner_check=True)
async def proxy_preview_session(
    thread_id: str,
    preview_id: str,
    request: Request,
    path: str = "",
) -> Response:
    manager = get_preview_session_manager(request)
    return await manager.proxy_request(
        user_id=_current_user_id(request),
        thread_id=thread_id,
        preview_id=preview_id,
        request=request,
        path=path,
    )


@router.post("/{thread_id}/artifacts/manifests/{artifact_id}/preview", response_model=PreviewSessionResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
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
    body = PreviewSessionCreateRequest(
        artifact_id=manifest.id,
        root_path=manifest.source_path,  # guaranteed non-None by manifest validator
        command=manifest.preview.command,  # guaranteed non-None for dev_server by manifest validator
        port=manifest.preview.port,
    )
    manager = get_preview_session_manager(request)
    return await manager.create_session(
        user_id=user_id,
        thread_id=thread_id,
        body=body,
    )
