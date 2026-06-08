import logging
import mimetypes
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.gateway.authz import require_permission
from app.gateway.path_utils import resolve_thread_virtual_path
from omniharness.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from omniharness.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["artifacts"])

ACTIVE_CONTENT_MIME_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
}

PREVIEW_MIME_TYPES = {
    "text/html",
    "text/css",
    "text/javascript",
    "application/javascript",
    "application/x-javascript",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/svg+xml",
    "image/webp",
}

PREVIEW_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "media-src 'self' data: blob:; "
        "frame-ancestors 'self'; "
        "base-uri 'none'; "
        "form-action 'none'"
    ),
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
}


def _build_content_disposition(disposition_type: str, filename: str) -> str:
    """Build an RFC 5987 encoded Content-Disposition header value."""
    return f"{disposition_type}; filename*=UTF-8''{quote(filename)}"


def _build_attachment_headers(filename: str, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Content-Disposition": _build_content_disposition("attachment", filename)}
    if extra_headers:
        headers.update(extra_headers)
    return headers


def _build_inline_headers(filename: str, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Content-Disposition": _build_content_disposition("inline", filename)}
    if extra_headers:
        headers.update(extra_headers)
    return headers


def _normalize_preview_virtual_path(path: str) -> str:
    stripped = path.lstrip("/")
    outputs_prefix = f"{VIRTUAL_PATH_PREFIX.lstrip('/')}/outputs"

    if stripped == outputs_prefix or stripped.startswith(outputs_prefix + "/"):
        return f"/{stripped}"

    if stripped == "outputs" or stripped.startswith("outputs/"):
        return f"{VIRTUAL_PATH_PREFIX}/{stripped}"

    raise HTTPException(status_code=403, detail="Preview path must be under /mnt/user-data/outputs")


def _resolve_preview_path(thread_id: str, artifact_path: str) -> Path:
    virtual_path = _normalize_preview_virtual_path(artifact_path)
    user_id = get_effective_user_id()
    paths = get_paths()

    try:
        actual_path = paths.resolve_virtual_path(thread_id, virtual_path, user_id=user_id)
    except ValueError as e:
        status = 403 if "traversal" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))

    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=user_id).resolve()

    try:
        actual_path.relative_to(outputs_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Preview path must stay inside thread outputs")

    return actual_path


def _preview_media_type(path: Path) -> str | None:
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type == "application/x-javascript":
        return "application/javascript"
    if mime_type in PREVIEW_MIME_TYPES:
        return mime_type
    return None


def is_text_file_by_content(path: Path, sample_size: int = 8192) -> bool:
    """Check if file is text by examining content for null bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
            # Text files shouldn't contain null bytes
            return b"\x00" not in chunk
    except Exception:
        return False


def _extract_file_from_skill_archive(zip_path: Path, internal_path: str) -> bytes | None:
    """Extract a file from a .skill ZIP archive.

    Args:
        zip_path: Path to the .skill file (ZIP archive).
        internal_path: Path to the file inside the archive (e.g., "SKILL.md").

    Returns:
        The file content as bytes, or None if not found.
    """
    if not zipfile.is_zipfile(zip_path):
        return None

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            # List all files in the archive
            namelist = zip_ref.namelist()

            # Try direct path first
            if internal_path in namelist:
                return zip_ref.read(internal_path)

            # Try with any top-level directory prefix (e.g., "skill-name/SKILL.md")
            for name in namelist:
                if name.endswith("/" + internal_path) or name == internal_path:
                    return zip_ref.read(name)

            # Not found
            return None
    except (zipfile.BadZipFile, KeyError):
        return None


@router.get(
    "/threads/{thread_id}/artifacts/preview/{artifact_path:path}",
    summary="Preview Artifact File",
    description="Safely preview static artifact files from a thread's outputs directory in an iframe.",
)
@require_permission("threads", "read", owner_check=True)
async def preview_artifact(thread_id: str, artifact_path: str, request: Request) -> Response:
    """Preview an artifact from the current user's thread outputs directory.

    This route is intentionally separate from the download/view artifact route:
    it only serves files under ``/mnt/user-data/outputs`` and allows a narrow
    set of static web asset types inline with iframe-oriented security headers.
    """
    actual_path = _resolve_preview_path(thread_id, artifact_path)

    logger.info(
        "Resolving artifact preview path: thread_id=%s, requested_path=%s, actual_path=%s",
        thread_id,
        artifact_path,
        actual_path,
    )

    if not actual_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_path}")

    if not actual_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {artifact_path}")

    media_type = _preview_media_type(actual_path)
    if media_type is None:
        raise HTTPException(status_code=415, detail="Artifact type is not supported for preview")

    return FileResponse(
        path=actual_path,
        filename=actual_path.name,
        media_type=media_type,
        headers=_build_inline_headers(actual_path.name, PREVIEW_SECURITY_HEADERS),
    )


@router.get(
    "/threads/{thread_id}/artifacts/{path:path}",
    summary="Get Artifact File",
    description="Retrieve an artifact file generated by the AI agent. Text and binary files can be viewed inline, while active web content is always downloaded.",
)
@require_permission("threads", "read", owner_check=True)
async def get_artifact(thread_id: str, path: str, request: Request, download: bool = False) -> Response:
    """Get an artifact file by its path.

    The endpoint automatically detects file types and returns appropriate content types.
    Use the `download` query parameter to force file download for non-active content.

    Args:
        thread_id: The thread ID.
        path: The artifact path with virtual prefix (e.g., mnt/user-data/outputs/file.txt).
        request: FastAPI request object (automatically injected).

    Returns:
        The file content as a FileResponse with appropriate content type:
        - Active content (HTML/XHTML/SVG): Served as download attachment
        - Text files: Plain text with proper MIME type
        - Binary files: Inline display with download option

    Raises:
        HTTPException:
            - 400 if path is invalid or not a file
            - 403 if access denied (path traversal detected)
            - 404 if file not found

    Query Parameters:
        download (bool): If true, forces attachment download for file types that are
            otherwise returned inline or as plain text. Active HTML/XHTML/SVG content
            is always downloaded regardless of this flag.

    Example:
        - Get text file inline: `/api/threads/abc123/artifacts/mnt/user-data/outputs/notes.txt`
        - Download file: `/api/threads/abc123/artifacts/mnt/user-data/outputs/data.csv?download=true`
        - Active web content such as `.html`, `.xhtml`, and `.svg` artifacts is always downloaded
    """
    # Check if this is a request for a file inside a .skill archive (e.g., xxx.skill/SKILL.md)
    if ".skill/" in path:
        # Split the path at ".skill/" to get the ZIP file path and internal path
        skill_marker = ".skill/"
        marker_pos = path.find(skill_marker)
        skill_file_path = path[: marker_pos + len(".skill")]  # e.g., "mnt/user-data/outputs/my-skill.skill"
        internal_path = path[marker_pos + len(skill_marker) :]  # e.g., "SKILL.md"

        actual_skill_path = resolve_thread_virtual_path(thread_id, skill_file_path)

        if not actual_skill_path.exists():
            raise HTTPException(status_code=404, detail=f"Skill file not found: {skill_file_path}")

        if not actual_skill_path.is_file():
            raise HTTPException(status_code=400, detail=f"Path is not a file: {skill_file_path}")

        # Extract the file from the .skill archive
        content = _extract_file_from_skill_archive(actual_skill_path, internal_path)
        if content is None:
            raise HTTPException(status_code=404, detail=f"File '{internal_path}' not found in skill archive")

        # Determine MIME type based on the internal file
        mime_type, _ = mimetypes.guess_type(internal_path)
        # Add cache headers to avoid repeated ZIP extraction (cache for 5 minutes)
        cache_headers = {"Cache-Control": "private, max-age=300"}
        download_name = Path(internal_path).name or actual_skill_path.stem
        if download or mime_type in ACTIVE_CONTENT_MIME_TYPES:
            return Response(content=content, media_type=mime_type or "application/octet-stream", headers=_build_attachment_headers(download_name, cache_headers))

        if mime_type and mime_type.startswith("text/"):
            return PlainTextResponse(content=content.decode("utf-8"), media_type=mime_type, headers=cache_headers)

        # Default to plain text for unknown types that look like text
        try:
            return PlainTextResponse(content=content.decode("utf-8"), media_type="text/plain", headers=cache_headers)
        except UnicodeDecodeError:
            return Response(content=content, media_type=mime_type or "application/octet-stream", headers=cache_headers)

    actual_path = resolve_thread_virtual_path(thread_id, path)

    logger.info(f"Resolving artifact path: thread_id={thread_id}, requested_path={path}, actual_path={actual_path}")

    if not actual_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {path}")

    if not actual_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {path}")

    mime_type, _ = mimetypes.guess_type(actual_path)

    if download:
        return FileResponse(path=actual_path, filename=actual_path.name, media_type=mime_type, headers=_build_attachment_headers(actual_path.name))

    # Always force download for active content types to prevent script execution
    # in the application origin when users open generated artifacts.
    if mime_type in ACTIVE_CONTENT_MIME_TYPES:
        return FileResponse(path=actual_path, filename=actual_path.name, media_type=mime_type, headers=_build_attachment_headers(actual_path.name))

    if mime_type and mime_type.startswith("text/"):
        return PlainTextResponse(content=actual_path.read_text(encoding="utf-8"), media_type=mime_type)

    if is_text_file_by_content(actual_path):
        return PlainTextResponse(content=actual_path.read_text(encoding="utf-8"), media_type=mime_type)

    return Response(content=actual_path.read_bytes(), media_type=mime_type, headers={"Content-Disposition": _build_content_disposition("inline", actual_path.name)})
