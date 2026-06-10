import json
import logging
import mimetypes
import os
import posixpath
import re
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.gateway.auth.config import get_auth_config
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
        "base-uri 'self'; "
        "form-action 'none'"
    ),
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
}

PREVIEW_TOKEN_ASSET_HEADERS = {
    "Cache-Control": "no-store",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

PREVIEW_TOKEN_TYPE = "artifact_preview"
PREVIEW_TOKEN_TTL_SECONDS = 10 * 60
MANIFEST_FILENAME = "artifact_manifest.json"

_HEAD_TAG_RE = re.compile(r"<head(?P<attrs>[^>]*)>", re.IGNORECASE)
_MANIFEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ROOT_RELATIVE_ATTR_RE = re.compile(
    r"(?P<prefix>\b(?:href|src|poster)\s*=\s*[\"'])(?P<url>/(?!/)[^\"']*)(?P<suffix>[\"'])",
    re.IGNORECASE,
)


class ArtifactManifestPreview(BaseModel):
    mode: Literal["static", "dev_server"] = "static"
    command: str | None = None
    port: int | None = None

    @model_validator(mode="after")
    def validate_preview(self):
        if self.mode == "static":
            return self
        if not self.command or not self.command.strip():
            raise ValueError("preview.command is required for dev_server previews")
        if self.port is not None and not (1 <= self.port <= 65535):
            raise ValueError("preview.port must be between 1 and 65535")
        return self


class ArtifactManifest(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    type: Literal["static_site", "web_app"]
    entrypoint: str | None = Field(default=None, min_length=1, max_length=512)
    root: str = Field(default=".", min_length=1, max_length=512)
    source_path: str | None = None
    preview: ArtifactManifestPreview = Field(default_factory=ArtifactManifestPreview)
    created_by: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_agent_fields(cls, data: Any) -> Any:
        """Normalize common agent-generated field name variants before validation.

        Agents sometimes write ``name`` instead of ``title``, omit ``id`` (relying
        on the folder name), or nest the workspace path as ``preview.cwd`` rather
        than the top-level ``source_path``.  This normalizer accepts those shapes
        so validation can still succeed.
        """
        if not isinstance(data, dict):
            return data

        # Accept "name" as alias for "title"
        if "title" not in data and "name" in data:
            data = {**data, "title": data["name"]}

        # Derive a safe "id" from "name" when "id" is missing
        if "id" not in data and "name" in data:
            raw = str(data["name"]).strip()
            slug = re.sub(r"[^A-Za-z0-9._-]", "-", raw)
            slug = re.sub(r"-{2,}", "-", slug).strip("-")[:128]
            if slug and _MANIFEST_ID_RE.fullmatch(slug):
                data = {**data, "id": slug}

        # Hoist preview.cwd to source_path when source_path is absent
        preview = data.get("preview")
        if isinstance(preview, dict) and "source_path" not in data and "cwd" in preview:
            data = {**data, "source_path": preview["cwd"]}

        # Infer source_path from workspace convention as a last resort.
        # Agents may omit source_path entirely when the project follows the
        # standard layout: /mnt/user-data/workspace/<artifact_id>.
        if not data.get("source_path"):
            artifact_id = data.get("id", "")
            if artifact_id and _MANIFEST_ID_RE.fullmatch(str(artifact_id)):
                data = {**data, "source_path": f"/mnt/user-data/workspace/{artifact_id}"}

        return data

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _MANIFEST_ID_RE.fullmatch(value):
            raise ValueError("id must be a safe artifact identifier")
        return value

    @field_validator("root")
    @classmethod
    def validate_root(cls, value: str) -> str:
        return _validate_relative_manifest_path(value, field_name="root", allow_dot=True)

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_relative_manifest_path(value, field_name="entrypoint", allow_dot=False)

    @model_validator(mode="after")
    def validate_manifest(self):
        if self.type == "static_site":
            if self.preview.mode != "static":
                raise ValueError("static_site manifests must use preview.mode=static")
            if not self.entrypoint:
                raise ValueError("entrypoint is required for static_site manifests")
        else:
            if self.preview.mode != "dev_server":
                raise ValueError("web_app manifests must use preview.mode=dev_server")
            if not self.source_path:
                raise ValueError("source_path is required for web_app manifests")
        return self


class ArtifactManifestResponse(ArtifactManifest):
    manifest_path: str
    root_path: str
    entrypoint_path: str | None = None


class ArtifactManifestListResponse(BaseModel):
    manifests: list[ArtifactManifestResponse]


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "dist",
        ".next",
        "build",
        ".nuxt",
        ".svelte-kit",
        "coverage",
        ".cache",
        ".parcel-cache",
        "out",
        ".turbo",
        ".vercel",
    }
)
_MAX_FILE_CONTENT_BYTES = 512 * 1024
_MAX_PROJECT_FILES = 2000


class ProjectFileEntry(BaseModel):
    path: str
    type: Literal["file", "dir"]
    size: int | None = None


class ProjectFilesResponse(BaseModel):
    artifact_id: str
    root: str
    files: list[ProjectFileEntry]


def _validate_relative_manifest_path(value: str, *, field_name: str, allow_dot: bool) -> str:
    if "\x00" in value or "\\" in value:
        raise ValueError(f"{field_name} must be a POSIX relative path")
    if value.startswith("/"):
        raise ValueError(f"{field_name} must be relative")
    raw_parts = value.split("/")
    if any(part in ("", "..") or (part == "." and value != ".") for part in raw_parts):
        raise ValueError(f"{field_name} must not contain traversal segments")

    normalized = posixpath.normpath(value)
    if normalized == ".":
        if allow_dot:
            return "."
        raise ValueError(f"{field_name} must reference a file")

    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"{field_name} must not contain traversal segments")

    return normalized


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


def _resolve_preview_path(thread_id: str, artifact_path: str, *, user_id: str | None = None) -> Path:
    virtual_path = _normalize_preview_virtual_path(artifact_path)
    user_id = user_id or get_effective_user_id()
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


def _ensure_path_inside(path: Path, root: Path, *, detail: str) -> None:
    try:
        path.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail=detail)


def _virtual_outputs_path(outputs_dir: Path, actual_path: Path) -> str:
    relative = actual_path.relative_to(outputs_dir).as_posix()
    return f"{VIRTUAL_PATH_PREFIX}/outputs/{relative}"


def _read_manifest_data(manifest_path: Path) -> dict:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"Invalid artifact manifest JSON: {e.msg}")

    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Artifact manifest must be a JSON object")
    return data


def _manifest_validation_error(exc: ValidationError) -> HTTPException:
    details = "; ".join(f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors())
    return HTTPException(status_code=422, detail=f"Invalid artifact manifest: {details}")


def _load_artifact_manifest(manifest_path: Path, *, outputs_dir: Path) -> ArtifactManifestResponse:
    outputs_dir = outputs_dir.resolve()
    resolved_manifest_path = manifest_path.resolve()
    _ensure_path_inside(
        resolved_manifest_path,
        outputs_dir,
        detail="Artifact manifest must stay inside thread outputs",
    )
    if not resolved_manifest_path.is_file():
        raise HTTPException(status_code=422, detail="Artifact manifest path is not a file")

    data = _read_manifest_data(resolved_manifest_path)
    try:
        manifest = ArtifactManifest.model_validate(data)
    except ValidationError as exc:
        raise _manifest_validation_error(exc)

    manifest_dir = resolved_manifest_path.parent
    root_path = (manifest_dir / manifest.root).resolve()
    _ensure_path_inside(root_path, outputs_dir, detail="Artifact manifest root must stay inside thread outputs")
    if not root_path.is_dir():
        raise HTTPException(status_code=422, detail="Artifact manifest root is not a directory")

    entrypoint_path: Path | None = None
    if manifest.entrypoint is not None:
        entrypoint_path = (root_path / manifest.entrypoint).resolve()
        _ensure_path_inside(
            entrypoint_path,
            outputs_dir,
            detail="Artifact manifest entrypoint must stay inside thread outputs",
        )
        _ensure_path_inside(
            entrypoint_path,
            root_path,
            detail="Artifact manifest entrypoint must stay inside manifest root",
        )
        if not entrypoint_path.is_file():
            raise HTTPException(status_code=422, detail="Artifact manifest entrypoint is not a file")

    return ArtifactManifestResponse(
        **manifest.model_dump(),
        manifest_path=_virtual_outputs_path(outputs_dir, resolved_manifest_path),
        root_path=_virtual_outputs_path(outputs_dir, root_path),
        entrypoint_path=_virtual_outputs_path(outputs_dir, entrypoint_path) if entrypoint_path is not None else None,
    )


def _iter_manifest_paths(outputs_dir: Path):
    if not outputs_dir.exists():
        return
    yield from outputs_dir.rglob(MANIFEST_FILENAME)


def _manifest_matches_artifact_id(manifest_path: Path, artifact_id: str) -> bool:
    if manifest_path.parent.name == artifact_id:
        return True
    try:
        data = _read_manifest_data(manifest_path.resolve())
    except HTTPException:
        return False
    return data.get("id") == artifact_id


def _get_outputs_dir(thread_id: str, *, user_id: str | None = None) -> Path:
    return get_paths().sandbox_outputs_dir(thread_id, user_id=user_id or get_effective_user_id()).resolve()


def get_artifact_manifest_for_preview(
    thread_id: str,
    artifact_id: str,
    *,
    user_id: str,
) -> ArtifactManifestResponse:
    """Load and validate a manifest by artifact_id; used by the preview session router."""
    outputs_dir = _get_outputs_dir(thread_id, user_id=user_id)
    for manifest_path in _iter_manifest_paths(outputs_dir):
        if not _manifest_matches_artifact_id(manifest_path, artifact_id):
            continue
        return _load_artifact_manifest(manifest_path, outputs_dir=outputs_dir)
    raise HTTPException(status_code=404, detail=f"Artifact manifest not found: {artifact_id}")


def _preview_virtual_parent(path: str) -> str:
    virtual_path = _normalize_preview_virtual_path(path)
    parent = virtual_path.rsplit("/", 1)[0]
    return parent if parent else f"{VIRTUAL_PATH_PREFIX}/outputs"


def _is_preview_path_inside_root(path: str, root: str) -> bool:
    normalized_path = _normalize_preview_virtual_path(path).rstrip("/")
    normalized_root = _normalize_preview_virtual_path(root).rstrip("/")
    return normalized_path == normalized_root or normalized_path.startswith(normalized_root + "/")


def _preview_token_path(thread_id: str, token: str, virtual_path: str) -> str:
    return f"/api/threads/{quote(thread_id, safe='')}/artifacts/preview-token/{quote(token, safe='')}{virtual_path}"


def _create_preview_token(thread_id: str, user_id: str, root_virtual_path: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "typ": PREVIEW_TOKEN_TYPE,
        "sub": user_id,
        "tid": thread_id,
        "root": _normalize_preview_virtual_path(root_virtual_path).rstrip("/"),
        "iat": now,
        "exp": now + timedelta(seconds=PREVIEW_TOKEN_TTL_SECONDS),
    }
    return jwt.encode(payload, get_auth_config().jwt_secret, algorithm="HS256")


def _decode_preview_token(token: str) -> dict[str, str]:
    try:
        payload = jwt.decode(token, get_auth_config().jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Preview token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid preview token")

    if payload.get("typ") != PREVIEW_TOKEN_TYPE:
        raise HTTPException(status_code=401, detail="Invalid preview token")

    user_id = payload.get("sub")
    thread_id = payload.get("tid")
    root = payload.get("root")
    if not isinstance(user_id, str) or not isinstance(thread_id, str) or not isinstance(root, str):
        raise HTTPException(status_code=401, detail="Invalid preview token")

    return {
        "user_id": user_id,
        "thread_id": thread_id,
        "root": _normalize_preview_virtual_path(root).rstrip("/"),
    }


def _rewrite_root_relative_preview_url(match: re.Match[str], *, thread_id: str, token: str, root_virtual_path: str) -> str:
    url = match.group("url")
    target_virtual_path = f"{root_virtual_path.rstrip('/')}{url}"
    return f"{match.group('prefix')}{_preview_token_path(thread_id, token, target_virtual_path)}{match.group('suffix')}"


def _rewrite_preview_html(
    html: str,
    *,
    thread_id: str,
    token: str,
    current_virtual_dir: str,
    root_virtual_path: str,
) -> str:
    base_href = _preview_token_path(thread_id, token, current_virtual_dir.rstrip("/") + "/")
    base_tag = f'<base href="{base_href}">'

    rewritten = _ROOT_RELATIVE_ATTR_RE.sub(
        lambda match: _rewrite_root_relative_preview_url(
            match,
            thread_id=thread_id,
            token=token,
            root_virtual_path=root_virtual_path,
        ),
        html,
    )

    if _HEAD_TAG_RE.search(rewritten):
        return _HEAD_TAG_RE.sub(lambda match: f"{match.group(0)}{base_tag}", rewritten, count=1)

    return f"{base_tag}{rewritten}"


def _preview_media_type(path: Path) -> str | None:
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type == "application/x-javascript":
        return "application/javascript"
    if mime_type in PREVIEW_MIME_TYPES:
        return mime_type
    return None


def _preview_headers_for(filename: str, media_type: str, *, is_token_route: bool) -> dict[str, str]:
    if is_token_route and media_type != "text/html":
        return _build_inline_headers(filename, PREVIEW_TOKEN_ASSET_HEADERS)
    return _build_inline_headers(filename, PREVIEW_SECURITY_HEADERS)


def _build_preview_response(
    thread_id: str,
    artifact_path: str,
    request: Request,
    *,
    user_id: str,
    preview_token: str | None = None,
    preview_root: str | None = None,
) -> Response:
    actual_path = _resolve_preview_path(thread_id, artifact_path, user_id=user_id)

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

    headers = _preview_headers_for(actual_path.name, media_type, is_token_route=preview_token is not None)

    if media_type == "text/html":
        root_virtual_path = preview_root or _preview_virtual_parent(artifact_path)
        token = preview_token or _create_preview_token(thread_id, user_id, root_virtual_path)
        html = actual_path.read_text(encoding="utf-8", errors="replace")
        rewritten_html = _rewrite_preview_html(
            html,
            thread_id=thread_id,
            token=token,
            current_virtual_dir=_preview_virtual_parent(artifact_path),
            root_virtual_path=root_virtual_path,
        )
        return Response(content=rewritten_html, media_type=media_type, headers=headers)

    return FileResponse(
        path=actual_path,
        filename=actual_path.name,
        media_type=media_type,
        headers=headers,
    )


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
    return _build_preview_response(
        thread_id,
        artifact_path,
        request,
        user_id=get_effective_user_id(),
    )


@router.get(
    "/threads/{thread_id}/artifacts/preview-token/{token}/{artifact_path:path}",
    summary="Preview Artifact File With Token",
    description="Serve nested static preview assets using a short-lived token minted by the main preview route.",
)
async def preview_artifact_with_token(thread_id: str, token: str, artifact_path: str, request: Request) -> Response:
    payload = _decode_preview_token(token)
    if payload["thread_id"] != thread_id:
        raise HTTPException(status_code=403, detail="Preview token does not match thread")

    if not _is_preview_path_inside_root(artifact_path, payload["root"]):
        raise HTTPException(status_code=403, detail="Preview token does not allow this path")

    return _build_preview_response(
        thread_id,
        artifact_path,
        request,
        user_id=payload["user_id"],
        preview_token=token,
        preview_root=payload["root"],
    )


@router.get(
    "/threads/{thread_id}/artifacts/manifests",
    summary="List Artifact Manifests",
    description="List validated project artifact manifests under a thread's outputs directory.",
)
@require_permission("threads", "read", owner_check=True)
async def list_artifact_manifests(thread_id: str, request: Request) -> ArtifactManifestListResponse:
    outputs_dir = _get_outputs_dir(thread_id)
    manifests: list[ArtifactManifestResponse] = []
    for manifest_path in _iter_manifest_paths(outputs_dir):
        try:
            manifests.append(_load_artifact_manifest(manifest_path, outputs_dir=outputs_dir))
        except HTTPException as exc:
            logger.warning(
                "Skipping invalid artifact manifest: thread_id=%s, manifest_path=%s, status=%s, detail=%s",
                thread_id,
                manifest_path,
                exc.status_code,
                exc.detail,
            )

    manifests.sort(key=lambda manifest: manifest.title.casefold())
    return ArtifactManifestListResponse(manifests=manifests)


@router.get(
    "/threads/{thread_id}/artifacts/manifests/{artifact_id}",
    summary="Get Artifact Manifest",
    description="Get a validated project artifact manifest by id.",
)
@require_permission("threads", "read", owner_check=True)
async def get_artifact_manifest(thread_id: str, artifact_id: str, request: Request) -> ArtifactManifestResponse:
    outputs_dir = _get_outputs_dir(thread_id)
    for manifest_path in _iter_manifest_paths(outputs_dir):
        if not _manifest_matches_artifact_id(manifest_path, artifact_id):
            continue
        return _load_artifact_manifest(manifest_path, outputs_dir=outputs_dir)

    raise HTTPException(status_code=404, detail=f"Artifact manifest not found: {artifact_id}")


def _resolve_project_root(thread_id: str, manifest: ArtifactManifestResponse, *, user_id: str) -> Path:
    """Resolve the filesystem root for a project's source files.

    Prefers source_path (workspace) over root_path (outputs manifest dir).
    """
    paths = get_paths()

    if manifest.source_path:
        try:
            candidate = paths.resolve_virtual_path(thread_id, manifest.source_path, user_id=user_id)
            if candidate.is_dir():
                return candidate
        except Exception:
            pass

    try:
        root = paths.resolve_virtual_path(thread_id, manifest.root_path, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Project root not accessible: {exc}")

    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Project root directory not found")

    return root


@router.get(
    "/threads/{thread_id}/projects/{artifact_id}/files",
    summary="List Project Files",
    description="List source files in a project artifact's root directory.",
)
@require_permission("threads", "read", owner_check=True)
async def list_project_files(thread_id: str, artifact_id: str, request: Request) -> ProjectFilesResponse:
    user_id = get_effective_user_id()
    manifest = get_artifact_manifest_for_preview(thread_id, artifact_id, user_id=user_id)
    root = _resolve_project_root(thread_id, manifest, user_id=user_id)

    files: list[ProjectFileEntry] = []
    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False, topdown=True):
        dir_path = Path(dirpath)
        rel_dir = dir_path.relative_to(root)

        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))

        for filename in sorted(filenames):
            if filename == MANIFEST_FILENAME and str(rel_dir) == ".":
                continue
            rel_path = filename if str(rel_dir) == "." else f"{rel_dir.as_posix()}/{filename}"
            try:
                size = (dir_path / filename).stat().st_size
            except Exception:
                size = None
            files.append(ProjectFileEntry(path=rel_path, type="file", size=size))
            if len(files) >= _MAX_PROJECT_FILES:
                break

        if len(files) >= _MAX_PROJECT_FILES:
            break

    return ProjectFilesResponse(
        artifact_id=artifact_id,
        root=manifest.source_path or manifest.root_path,
        files=files,
    )


@router.get(
    "/threads/{thread_id}/projects/{artifact_id}/files/content",
    summary="Get Project File Content",
    description="Read a source file from a project artifact.",
)
@require_permission("threads", "read", owner_check=True)
async def get_project_file_content(thread_id: str, artifact_id: str, request: Request, path: str) -> Response:
    if not path or "\x00" in path or "\\" in path:
        raise HTTPException(status_code=400, detail="Invalid file path")
    if path.startswith("/"):
        raise HTTPException(status_code=400, detail="Path must be relative")
    parts = path.split("/")
    if any(part in ("", "..") for part in parts):
        raise HTTPException(status_code=400, detail="Path traversal is not allowed")

    user_id = get_effective_user_id()
    manifest = get_artifact_manifest_for_preview(thread_id, artifact_id, user_id=user_id)
    root = _resolve_project_root(thread_id, manifest, user_id=user_id)

    file_path = (root / path).resolve()
    try:
        file_path.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Path escapes project root")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    if not file_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {path}")

    if file_path.stat().st_size > _MAX_FILE_CONTENT_BYTES:
        raise HTTPException(status_code=413, detail="File too large for inline viewing (max 512 KB)")

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}")

    return PlainTextResponse(content=content)


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
