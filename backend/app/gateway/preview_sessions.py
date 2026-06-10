from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from omniharness.community.aio_sandbox.aio_sandbox import AioSandbox
from omniharness.community.aio_sandbox.aio_sandbox_provider import (
    AioSandboxProvider,
)
from omniharness.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from omniharness.sandbox.sandbox_provider import get_sandbox_provider

logger = logging.getLogger(__name__)

PreviewSessionStatus = Literal["starting", "running", "failed", "stopped"]

_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HTML_HEAD_RE = re.compile(r"<head(?P<attrs>[^>]*)>", re.IGNORECASE)
_HTML_ROOT_RELATIVE_ATTR_RE = re.compile(
    r"(?P<prefix>\b(?:href|src|poster|action)\s*=\s*[\"'])(?P<url>/(?!/)[^\"']*)(?P<suffix>[\"'])",
    re.IGNORECASE,
)
_CSS_ROOT_RELATIVE_URL_RE = re.compile(
    r"url\(\s*(?P<q>[\"']?)(?P<url>/(?!/)[^)\"'\s]*)(?P=q)\s*\)",
    re.IGNORECASE,
)
_JS_ROOT_RELATIVE_IMPORT_RE = re.compile(
    r"""(?P<prefix>\b(?:from|import)\s*\(?\s*["'])(?P<url>/(?!/)[^"'\s]*)(?P<suffix>["'])""",
)
_HTML_INLINE_MODULE_SCRIPT_RE = re.compile(
    r"(<script\b[^>]*\btype\s*=\s*[\"']module[\"'][^>]*>)(.*?)(</script\s*>)",
    re.IGNORECASE | re.DOTALL,
)
_PORT_PATTERNS = (
    re.compile(r"https?://(?:127\.0\.0\.1|0\.0\.0\.0|localhost):(?P<port>\d{2,5})", re.IGNORECASE),
    re.compile(r"\b(?:ready on|listening on|local:|network:)\D+(?P<port>\d{2,5})", re.IGNORECASE),
)

_WORKSPACE_PREFIX = f"{VIRTUAL_PATH_PREFIX}/workspace"

# Patterns for package-manager script runners that need deps installed first.
_NPM_RUN_RE = re.compile(r"\bnpm\s+(?:run|start)\b")
_PNPM_RUN_RE = re.compile(r"\bpnpm\s+(?:run\s+)?\S")
_YARN_RUN_RE = re.compile(r"\byarn\s+(?:run\s+)?\S")
_BUN_RUN_RE = re.compile(r"\bbun\s+(?:run\s+)?\S")


def _maybe_prepend_install(command: str) -> str:
    """Prepend a conditional dependency-install step for package-manager script runners.

    Only installs if node_modules is absent, so repeat starts are fast.
    Handles npm, pnpm, yarn, and bun.
    """
    if _NPM_RUN_RE.search(command):
        return f"([ -d node_modules ] || npm install --no-fund --no-audit 2>&1) && {command}"
    if _PNPM_RUN_RE.search(command):
        return f"([ -d node_modules ] || pnpm install 2>&1) && {command}"
    if _YARN_RUN_RE.search(command):
        return f"([ -d node_modules ] || yarn install 2>&1) && {command}"
    if _BUN_RUN_RE.search(command):
        return f"([ -d node_modules ] || bun install 2>&1) && {command}"
    return command


_OUTPUTS_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs"
_DEFAULT_IDLE_TIMEOUT_SECONDS = 15 * 60
_CLEANUP_INTERVAL_SECONDS = 30
_MIN_ALLOWED_PORT = 1024
_MAX_ALLOWED_PORT = 65535
_NO_CHANGE_TIMEOUT_SECONDS = 24 * 60 * 60
_HOP_BY_HOP_REQUEST_HEADERS = {
    "accept-encoding",
    "connection",
    "content-length",
    "cookie",
    "host",
    "transfer-encoding",
}
_HOP_BY_HOP_RESPONSE_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "set-cookie",
    "transfer-encoding",
}


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _isoformat(value: datetime) -> str:
    return value.isoformat()


def _normalize_workspace_virtual_path(path: str) -> str:
    stripped = path.strip().rstrip("/")
    if not stripped:
        raise HTTPException(status_code=422, detail="root_path is required")

    normalized = stripped
    if normalized.startswith("/"):
        normalized = normalized
    elif normalized == "workspace" or normalized.startswith("workspace/"):
        normalized = f"{VIRTUAL_PATH_PREFIX}/{normalized}"
    elif normalized == _WORKSPACE_PREFIX.lstrip("/") or normalized.startswith(_WORKSPACE_PREFIX.lstrip("/") + "/"):
        normalized = f"/{normalized}"

    if normalized != _WORKSPACE_PREFIX and not normalized.startswith(_WORKSPACE_PREFIX + "/"):
        raise HTTPException(
            status_code=422,
            detail=f"root_path must stay under {_WORKSPACE_PREFIX}",
        )

    return normalized


def _ensure_workspace_root(
    *,
    thread_id: str,
    user_id: str,
    virtual_path: str,
) -> Path:
    paths = get_paths()
    actual_path = paths.resolve_virtual_path(thread_id, virtual_path, user_id=user_id)
    workspace_root = paths.sandbox_work_dir(thread_id, user_id=user_id).resolve()

    try:
        actual_path.relative_to(workspace_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"root_path must stay under {_WORKSPACE_PREFIX}",
        ) from exc

    if not actual_path.exists() or not actual_path.is_dir():
        raise HTTPException(status_code=422, detail="root_path must reference an existing directory")

    return actual_path


def _normalize_workspace_or_outputs_virtual_path(path: str) -> str:
    """Like _normalize_workspace_virtual_path but also accepts /mnt/user-data/outputs paths.

    Used for manifest-based previews where agents may place projects in outputs instead of workspace.
    Both locations are scoped to the user's thread data, so the security boundary is maintained.
    """
    stripped = path.strip().rstrip("/")
    if not stripped:
        raise HTTPException(status_code=422, detail="root_path is required")

    normalized = stripped
    if not normalized.startswith("/"):
        for prefix in (_WORKSPACE_PREFIX.lstrip("/"), _OUTPUTS_PREFIX.lstrip("/")):
            if normalized == prefix or normalized.startswith(prefix + "/"):
                normalized = f"/{normalized}"
                break
        else:
            for short in ("workspace", "outputs"):
                if normalized == short or normalized.startswith(short + "/"):
                    normalized = f"{VIRTUAL_PATH_PREFIX}/{normalized}"
                    break

    is_workspace = normalized == _WORKSPACE_PREFIX or normalized.startswith(_WORKSPACE_PREFIX + "/")
    is_outputs = normalized == _OUTPUTS_PREFIX or normalized.startswith(_OUTPUTS_PREFIX + "/")
    if not is_workspace and not is_outputs:
        raise HTTPException(
            status_code=422,
            detail=f"root_path must stay under {_WORKSPACE_PREFIX} or {_OUTPUTS_PREFIX}",
        )

    return normalized


def _ensure_workspace_or_outputs_root(
    *,
    thread_id: str,
    user_id: str,
    virtual_path: str,
) -> Path:
    """Validate root_path for manifest-based previews; accepts workspace or outputs directories."""
    paths = get_paths()
    actual_path = paths.resolve_virtual_path(thread_id, virtual_path, user_id=user_id)
    user_data_root = paths.sandbox_user_data_dir(thread_id, user_id=user_id).resolve()

    try:
        actual_path.relative_to(user_data_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"root_path must stay under {VIRTUAL_PATH_PREFIX}",
        ) from exc

    if not actual_path.exists() or not actual_path.is_dir():
        raise HTTPException(status_code=422, detail="root_path must reference an existing directory")

    return actual_path


def _validate_command(command: str) -> str:
    normalized = command.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="command is required")
    if "\x00" in normalized:
        raise HTTPException(status_code=422, detail="command contains invalid characters")
    return normalized


def _validate_port(port: int | None) -> int:
    if port is None:
        return 0
    if not (_MIN_ALLOWED_PORT <= port <= _MAX_ALLOWED_PORT):
        raise HTTPException(
            status_code=422,
            detail=f"port must be between {_MIN_ALLOWED_PORT} and {_MAX_ALLOWED_PORT}",
        )
    return port


def _detect_port(output: str) -> int | None:
    for pattern in _PORT_PATTERNS:
        match = pattern.search(output)
        if not match:
            continue
        try:
            port = int(match.group("port"))
        except (TypeError, ValueError):
            continue
        if _MIN_ALLOWED_PORT <= port <= _MAX_ALLOWED_PORT:
            return port
    return None


def _rewrite_proxy_location(location: str, proxy_root: str, port: int) -> str:
    for prefix in (
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
        f"http://0.0.0.0:{port}",
        f"https://127.0.0.1:{port}",
        f"https://localhost:{port}",
        f"https://0.0.0.0:{port}",
    ):
        if location.startswith(prefix):
            suffix = location[len(prefix) :]
            return f"{proxy_root}{suffix or '/'}"
    if location.startswith("/"):
        return f"{proxy_root}{location}"
    return location


def _rewrite_root_relative_html_urls(html: str, proxy_root: str) -> str:
    rewritten = _HTML_ROOT_RELATIVE_ATTR_RE.sub(
        lambda match: f"{match.group('prefix')}{proxy_root}{match.group('url')}{match.group('suffix')}",
        html,
    )
    # Rewrite root-relative ES module import paths inside inline <script type="module"> blocks.
    # Static import statements are resolved by the JS engine before any fetch/XHR shim runs,
    # so they must be textually rewritten at the HTML level.
    return _HTML_INLINE_MODULE_SCRIPT_RE.sub(
        lambda m: f"{m.group(1)}{_rewrite_root_relative_js_imports(m.group(2), proxy_root)}{m.group(3)}",
        rewritten,
    )


def _rewrite_root_relative_css_urls(css: str, proxy_root: str) -> str:
    return _CSS_ROOT_RELATIVE_URL_RE.sub(
        lambda m: f"url({m.group('q')}{proxy_root}{m.group('url')}{m.group('q')})",
        css,
    )


def _rewrite_root_relative_js_imports(js: str, proxy_root: str) -> str:
    return _JS_ROOT_RELATIVE_IMPORT_RE.sub(
        lambda m: f"{m.group('prefix')}{proxy_root}{m.group('url')}{m.group('suffix')}",
        js,
    )


def _preview_html_shim(proxy_root: str) -> str:
    proxy_root_json = json.dumps(proxy_root)
    return (
        "<script>"
        "(function(){"
        f"const proxyRoot={proxy_root_json};"
        "const rewrite=function(value){"
        "if(typeof value!=='string'||!value||value.startsWith('//')||!value.startsWith('/')) return value;"
        "if(value===proxyRoot||value.startsWith(proxyRoot+'/')) return value;"
        "return proxyRoot+value;"
        "};"
        "const originalFetch=window.fetch.bind(window);"
        "window.fetch=function(input,init){"
        "if(typeof input==='string'){return originalFetch(rewrite(input),init);}"
        "if(input instanceof URL){return originalFetch(new URL(rewrite(input.pathname+input.search+input.hash),window.location.origin),init);}"
        "if(input instanceof Request){const url=new URL(input.url);const rewritten=rewrite(url.pathname+url.search+url.hash);if(rewritten!==url.pathname+url.search+url.hash){input=new Request(window.location.origin+rewritten,input);}}"
        "return originalFetch(input,init);"
        "};"
        "const originalOpen=XMLHttpRequest.prototype.open;"
        "XMLHttpRequest.prototype.open=function(method,url){if(typeof url==='string'){arguments[1]=rewrite(url);}return originalOpen.apply(this,arguments);};"
        "const patchHistory=function(name){const original=history[name].bind(history);history[name]=function(state,title,url){if(typeof url==='string'){url=rewrite(url);}return original(state,title,url);};};"
        "patchHistory('pushState');"
        "patchHistory('replaceState');"
        # Intercept setAttribute so React's DOM reconciler doesn't slip root-relative paths past us
        "const _origSetAttr=Element.prototype.setAttribute;"
        "Element.prototype.setAttribute=function(name,value){"
        "if(typeof value==='string'&&(name==='href'||name==='src'||name==='action'||name==='poster')){value=rewrite(value);}"
        "return _origSetAttr.call(this,name,value);};"
        # Intercept the IDL property setters (e.g. link.href=...) used by React's preload() hint system
        "const _pp=function(proto,prop){"
        "if(!proto)return;"
        "const d=Object.getOwnPropertyDescriptor(proto,prop);"
        "if(d&&d.set){Object.defineProperty(proto,prop,Object.assign({},d,{set:function(v){d.set.call(this,typeof v==='string'?rewrite(v):v);}}));}};"
        "_pp(HTMLLinkElement.prototype,'href');"
        "_pp(HTMLAnchorElement.prototype,'href');"
        "_pp(HTMLScriptElement.prototype,'src');"
        "_pp(HTMLImageElement.prototype,'src');"
        "_pp(HTMLIFrameElement.prototype,'src');"
        "_pp(HTMLVideoElement.prototype,'src');"
        "_pp(HTMLSourceElement.prototype,'src');"
        "window.__OMNI_HARNESS_PREVIEW_PROXY_ROOT__=proxyRoot;"
        "})();"
        "</script>"
    )


def _inject_preview_shim(html: str, proxy_root: str) -> str:
    base_tag = f'<base href="{proxy_root}/">'
    shim = _preview_html_shim(proxy_root)
    rewritten = _rewrite_root_relative_html_urls(html, proxy_root)
    if _HTML_HEAD_RE.search(rewritten):
        return _HTML_HEAD_RE.sub(lambda match: f"{match.group(0)}{base_tag}{shim}", rewritten, count=1)
    return f"{base_tag}{shim}{rewritten}"


def _sanitize_proxy_request_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in request.headers.items():
        lowered = key.lower()
        if lowered in _HOP_BY_HOP_REQUEST_HEADERS or lowered.startswith("x-forwarded-"):
            continue
        headers[key] = value
    return headers


def _sanitize_proxy_response_headers(headers: dict[str, str], *, proxy_root: str, port: int) -> dict[str, str]:
    sanitized: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in _HOP_BY_HOP_RESPONSE_HEADERS:
            continue
        if lowered == "location":
            sanitized[key] = _rewrite_proxy_location(value, proxy_root, port)
            continue
        sanitized[key] = value
    return sanitized


class PreviewSessionCreateRequest(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=128)
    root_path: str = Field(min_length=1, max_length=512)
    command: str = Field(min_length=1, max_length=4096)
    port: int | None = Field(default=None, ge=1, le=65535)

    @field_validator("artifact_id")
    @classmethod
    def validate_artifact_id(cls, value: str) -> str:
        if not _ARTIFACT_ID_RE.fullmatch(value):
            raise ValueError("artifact_id must be a safe artifact identifier")
        return value


class PreviewSessionResponse(BaseModel):
    id: str
    user_id: str
    thread_id: str
    artifact_id: str
    root_path: str
    command: str
    port: int | None = None
    status: PreviewSessionStatus
    proxy_url: str
    logs_url: str
    created_at: str
    updated_at: str
    expires_at: str
    exit_code: int | None = None
    error: str | None = None


class PreviewSessionLogsResponse(BaseModel):
    preview_id: str
    thread_id: str
    status: PreviewSessionStatus
    logs: str
    exit_code: int | None = None
    error: str | None = None


@dataclass
class _PreviewSessionRecord:
    id: str
    user_id: str
    thread_id: str
    artifact_id: str
    root_path: str
    command: str
    port: int
    sandbox_id: str
    shell_session_id: str
    status: PreviewSessionStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    exit_code: int | None = None
    error: str | None = None

    def proxy_url(self) -> str:
        return f"/api/threads/{self.thread_id}/previews/{self.id}/proxy"

    def logs_url(self) -> str:
        return f"/api/threads/{self.thread_id}/previews/{self.id}/logs"

    def to_response(self) -> PreviewSessionResponse:
        return PreviewSessionResponse(
            id=self.id,
            user_id=self.user_id,
            thread_id=self.thread_id,
            artifact_id=self.artifact_id,
            root_path=self.root_path,
            command=self.command,
            port=self.port or None,
            status=self.status,
            proxy_url=self.proxy_url(),
            logs_url=self.logs_url(),
            created_at=_isoformat(self.created_at),
            updated_at=_isoformat(self.updated_at),
            expires_at=_isoformat(self.expires_at),
            exit_code=self.exit_code,
            error=self.error,
        )


class PreviewSessionManager:
    def __init__(self, *, idle_timeout_seconds: int = _DEFAULT_IDLE_TIMEOUT_SECONDS) -> None:
        self._idle_timeout_seconds = idle_timeout_seconds
        self._sessions: dict[str, _PreviewSessionRecord] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        self._closed = False

    def start(self) -> None:
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def close(self) -> None:
        self._closed = True
        task = self._cleanup_task
        self._cleanup_task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        session_ids = list(self._sessions)
        for session_id in session_ids:
            with contextlib.suppress(Exception):
                await self._stop_and_cleanup_session(session_id)

    async def _cleanup_loop(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
                await self.cleanup_expired_sessions()
        except asyncio.CancelledError:
            raise

    async def cleanup_expired_sessions(self) -> None:
        now = _now_utc()
        expired_ids = [session.id for session in self._sessions.values() if session.expires_at <= now]
        for session_id in expired_ids:
            with contextlib.suppress(Exception):
                await self._stop_and_cleanup_session(session_id)

    async def list_sessions(self, *, user_id: str, thread_id: str) -> list[PreviewSessionResponse]:
        await self.cleanup_expired_sessions()
        responses: list[PreviewSessionResponse] = []
        for session in list(self._sessions.values()):
            if session.user_id != user_id or session.thread_id != thread_id:
                continue
            with contextlib.suppress(Exception):
                await self._refresh_session(session, touch=False)
            responses.append(session.to_response())
        responses.sort(key=lambda item: item.created_at)
        return responses

    async def create_session(
        self,
        *,
        user_id: str,
        thread_id: str,
        body: PreviewSessionCreateRequest,
    ) -> PreviewSessionResponse:
        root_path = _normalize_workspace_virtual_path(body.root_path)
        _ensure_workspace_root(thread_id=thread_id, user_id=user_id, virtual_path=root_path)
        command = _validate_command(body.command)
        port = _validate_port(body.port)

        existing = next(
            (session for session in self._sessions.values() if session.user_id == user_id and session.thread_id == thread_id and session.artifact_id == body.artifact_id),
            None,
        )
        if existing is not None and existing.status in {"running", "starting"}:
            await self._refresh_session(existing)
            if existing.status in {"running", "starting"}:
                return existing.to_response()
            # Sandbox or process is gone — fall through to restart the session below

        session = existing or self._new_session(
            user_id=user_id,
            thread_id=thread_id,
            artifact_id=body.artifact_id,
            root_path=root_path,
            command=command,
            port=port,
        )
        session.root_path = root_path
        session.command = command
        session.port = port
        session.error = None
        session.exit_code = None
        self._sessions[session.id] = session

        await self._start_session(session)
        return session.to_response()

    async def create_session_from_manifest(
        self,
        *,
        user_id: str,
        thread_id: str,
        body: PreviewSessionCreateRequest,
    ) -> PreviewSessionResponse:
        """Like create_session but accepts workspace OR outputs as root_path.

        Used by manifest-based preview endpoints where agents may place the project
        in /mnt/user-data/outputs instead of /mnt/user-data/workspace. Both are
        scoped to the user's thread data so the security boundary is maintained.
        """
        root_path = _normalize_workspace_or_outputs_virtual_path(body.root_path)
        _ensure_workspace_or_outputs_root(thread_id=thread_id, user_id=user_id, virtual_path=root_path)
        command = _validate_command(body.command)
        port = _validate_port(body.port)

        existing = next(
            (session for session in self._sessions.values() if session.user_id == user_id and session.thread_id == thread_id and session.artifact_id == body.artifact_id),
            None,
        )
        if existing is not None and existing.status in {"running", "starting"}:
            await self._refresh_session(existing)
            if existing.status in {"running", "starting"}:
                return existing.to_response()
            # Sandbox or process is gone — fall through to restart the session below

        session = existing or self._new_session(
            user_id=user_id,
            thread_id=thread_id,
            artifact_id=body.artifact_id,
            root_path=root_path,
            command=command,
            port=port,
        )
        session.root_path = root_path
        session.command = command
        session.port = port
        session.error = None
        session.exit_code = None
        self._sessions[session.id] = session

        await self._start_session(session)
        return session.to_response()

    async def get_session(self, *, user_id: str, thread_id: str, preview_id: str) -> PreviewSessionResponse:
        session = self._require_session(user_id=user_id, thread_id=thread_id, preview_id=preview_id)
        await self._refresh_session(session)
        return session.to_response()

    async def get_logs(
        self,
        *,
        user_id: str,
        thread_id: str,
        preview_id: str,
    ) -> PreviewSessionLogsResponse:
        session = self._require_session(user_id=user_id, thread_id=thread_id, preview_id=preview_id)
        logs = await self._refresh_session(session)
        return PreviewSessionLogsResponse(
            preview_id=session.id,
            thread_id=session.thread_id,
            status=session.status,
            logs=logs,
            exit_code=session.exit_code,
            error=session.error,
        )

    async def stop_session(self, *, user_id: str, thread_id: str, preview_id: str) -> PreviewSessionResponse:
        session = self._require_session(user_id=user_id, thread_id=thread_id, preview_id=preview_id)
        try:
            sandbox = await self._get_sandbox_for_existing_session(session)
        except Exception:
            # Sandbox is gone — session is already effectively stopped
            session.status = "stopped"
            session.error = None
            session.updated_at = _now_utc()
            return session.to_response()
        await asyncio.to_thread(sandbox.kill_shell_session, session.shell_session_id)
        await self._refresh_session(session)
        if session.status == "failed":
            session.status = "stopped"
            session.error = None
            session.updated_at = _now_utc()
        return session.to_response()

    async def restart_session(self, *, user_id: str, thread_id: str, preview_id: str) -> PreviewSessionResponse:
        session = self._require_session(user_id=user_id, thread_id=thread_id, preview_id=preview_id)
        await self._restart_session(session)
        return session.to_response()

    async def stop_thread_sessions(self, *, thread_id: str) -> None:
        matching_ids = [session.id for session in self._sessions.values() if session.thread_id == thread_id]
        for session_id in matching_ids:
            with contextlib.suppress(Exception):
                await self._stop_and_cleanup_session(session_id)

    async def proxy_request(
        self,
        *,
        user_id: str,
        thread_id: str,
        preview_id: str,
        request: Request,
        path: str,
    ) -> Response:
        session = self._require_session(user_id=user_id, thread_id=thread_id, preview_id=preview_id)
        # Skip the expensive per-request refresh for already-running sessions.
        # The status-polling endpoint (GET /previews and GET /previews/{id}/logs)
        # refreshes status every ~3 s via background polling. Probing on every
        # proxied asset request (HTML, JS chunks, CSS, images) runs concurrent
        # nodejs.execute_code calls inside the shared container and overloads the
        # sandbox executor, causing probe failures that flip the status back to
        # "starting" and 409s for all subsequent asset requests.
        if session.status != "running":
            await self._refresh_session(session)
        if session.status == "stopped":
            raise HTTPException(status_code=409, detail="Preview session is stopped")
        if session.status == "failed":
            raise HTTPException(status_code=502, detail=session.error or "Preview session failed")
        if session.port == 0:
            raise HTTPException(status_code=409, detail="Preview session has not exposed a port yet")

        sandbox = await self._get_sandbox_for_existing_session(session)
        proxy_path = f"/{path.lstrip('/')}" if path else "/"
        if request.url.query:
            proxy_path = f"{proxy_path}?{request.url.query}"
        body = await request.body()
        try:
            forwarded = await asyncio.to_thread(
                sandbox.fetch_local_url,
                port=session.port,
                path=proxy_path,
                method=request.method,
                headers=_sanitize_proxy_request_headers(request),
                body=body or None,
            )
        except Exception as exc:
            # Forward failed — refresh to detect any process exit, then surface a 502
            with contextlib.suppress(Exception):
                await self._refresh_session(session, touch=False)
            raise HTTPException(status_code=502, detail=f"Preview request failed: {exc}") from exc

        session.updated_at = _now_utc()
        session.expires_at = session.updated_at + timedelta(seconds=self._idle_timeout_seconds)
        proxy_root = session.proxy_url()
        headers = _sanitize_proxy_response_headers(
            dict(forwarded["headers"]),
            proxy_root=proxy_root,
            port=session.port,
        )
        payload = forwarded["body"]
        content_type = headers.get("content-type", "")
        if "text/html" in content_type:
            html = payload.decode("utf-8", errors="replace")
            payload = _inject_preview_shim(html, proxy_root).encode("utf-8")
        elif "text/css" in content_type:
            css = payload.decode("utf-8", errors="replace")
            payload = _rewrite_root_relative_css_urls(css, proxy_root).encode("utf-8")
        elif "javascript" in content_type or "application/x-typescript" in content_type:
            js = payload.decode("utf-8", errors="replace")
            payload = _rewrite_root_relative_js_imports(js, proxy_root).encode("utf-8")

        return Response(
            content=payload,
            status_code=int(forwarded["status"]),
            headers=headers,
            media_type=None,
        )

    def _new_session(
        self,
        *,
        user_id: str,
        thread_id: str,
        artifact_id: str,
        root_path: str,
        command: str,
        port: int,
    ) -> _PreviewSessionRecord:
        now = _now_utc()
        session_id = f"preview_{thread_id}_{artifact_id}_{now.strftime('%H%M%S%f')}"
        return _PreviewSessionRecord(
            id=session_id,
            user_id=user_id,
            thread_id=thread_id,
            artifact_id=artifact_id,
            root_path=root_path,
            command=command,
            port=port,
            sandbox_id="",
            shell_session_id=session_id,
            status="starting",
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(seconds=self._idle_timeout_seconds),
        )

    def _require_session(
        self,
        *,
        user_id: str,
        thread_id: str,
        preview_id: str,
    ) -> _PreviewSessionRecord:
        session = self._sessions.get(preview_id)
        if session is None or session.user_id != user_id or session.thread_id != thread_id:
            raise HTTPException(status_code=404, detail=f"Preview session not found: {preview_id}")
        return session

    async def _start_session(self, session: _PreviewSessionRecord) -> None:
        sandbox_id, sandbox = await self._get_or_create_sandbox(thread_id=session.thread_id)
        session.sandbox_id = sandbox_id

        # Clean up any existing shell session with the same ID before (re)creating it.
        # On the restart path, create_session_from_manifest reuses the existing session
        # object (same shell_session_id), so the old completed/terminated shell session
        # must be removed first. For brand-new sessions the ID doesn't exist yet so
        # these are harmless no-ops.
        with contextlib.suppress(Exception):
            await asyncio.to_thread(sandbox.kill_shell_session, session.shell_session_id)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(sandbox.cleanup_shell_session, session.shell_session_id)

        # Kill any other running sessions for this thread that bind the same port so we
        # don't hit EADDRINUSE when the container is shared across multiple artifacts.
        if session.port != 0:
            for other in list(self._sessions.values()):
                if other.id != session.id and other.thread_id == session.thread_id and other.port == session.port and other.status in {"running", "starting"}:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(sandbox.kill_shell_session, other.shell_session_id)
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(sandbox.cleanup_shell_session, other.shell_session_id)
                    other.status = "stopped"
                    other.error = None
                    other.updated_at = _now_utc()
                    logger.debug("stopped conflicting preview session %s (port %d) for thread %s", other.id, other.port, other.thread_id)

        # Verify the project root actually exists inside the sandbox container before
        # trying to start the dev server. The manifest router's host-side is_dir() check
        # can return True while the container doesn't see the directory (e.g. if the
        # agent put files in a different location, or the sandbox was recreated with a
        # fresh ephemeral layer). Catching this here produces a clear error instead of
        # the opaque "bash: cd: No such file or directory" that bubbles up otherwise.
        dir_check = await asyncio.to_thread(
            sandbox.execute_command,
            f"test -d {shlex.quote(session.root_path)} && echo __dir_ok__ || echo __dir_missing__",
        )
        if "__dir_ok__" not in (dir_check or ""):
            session.status = "failed"
            session.error = f"Project directory not found inside the sandbox: {session.root_path}. Ask the agent to recreate the project files in the workspace."
            session.updated_at = _now_utc()
            session.expires_at = session.updated_at + timedelta(seconds=self._idle_timeout_seconds)
            return

        await asyncio.to_thread(
            sandbox.create_shell_session,
            session_id=session.shell_session_id,
            exec_dir=session.root_path,
            no_change_timeout=_NO_CHANGE_TIMEOUT_SECONDS,
        )
        # Prefix with an explicit cd so the dev server always runs from the
        # project root. The exec_dir param is silently ignored in async mode
        # (falls back to session CWD = /home/gem), so we embed the cd in the
        # command itself as a reliable alternative.
        effective_command = f"cd {shlex.quote(session.root_path)} && {_maybe_prepend_install(session.command)}"
        result = await asyncio.to_thread(
            sandbox.start_shell_command,
            session_id=session.shell_session_id,
            command=effective_command,
            exec_dir=session.root_path,
            no_change_timeout=_NO_CHANGE_TIMEOUT_SECONDS,
        )
        session.status = "starting" if result["status"] == "running" else "failed"
        session.updated_at = _now_utc()
        session.expires_at = session.updated_at + timedelta(seconds=self._idle_timeout_seconds)
        session.exit_code = result.get("exit_code")
        if result["status"] != "running":
            session.error = result.get("output") or "Preview command failed to start"
        await self._refresh_session(session, touch=False)

    async def _restart_session(self, session: _PreviewSessionRecord) -> None:
        sandbox = await self._get_sandbox_for_existing_session(session)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(sandbox.kill_shell_session, session.shell_session_id)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(sandbox.cleanup_shell_session, session.shell_session_id)
        await self._start_session(session)

    async def _stop_and_cleanup_session(self, preview_id: str) -> None:
        session = self._sessions.get(preview_id)
        if session is None:
            return
        try:
            sandbox = await self._get_sandbox_for_existing_session(session)
        except Exception:
            self._sessions.pop(preview_id, None)
            return
        try:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(sandbox.kill_shell_session, session.shell_session_id)
            with contextlib.suppress(Exception):
                await asyncio.to_thread(sandbox.cleanup_shell_session, session.shell_session_id)
        finally:
            self._sessions.pop(preview_id, None)

    async def _refresh_session(self, session: _PreviewSessionRecord, *, touch: bool = True) -> str:
        try:
            sandbox = await self._get_sandbox_for_existing_session(session)
        except Exception as exc:
            # Sandbox is gone (container restarted, provider changed, etc.).
            # Mark as failed so callers can decide whether to recreate rather than propagating a 404.
            detail = getattr(exc, "detail", None) or str(exc)
            session.status = "failed"
            session.error = str(detail)
            session.updated_at = _now_utc()
            logger.debug("sandbox lookup failed for %s: %s", session.id, exc)
            return session.error
        try:
            view = await asyncio.to_thread(sandbox.view_shell_session, session.shell_session_id)
        except Exception as exc:
            # Shell session is gone (sandbox restarted, session cleaned up, etc.).
            # Mark as failed with the reason rather than propagating a 500.
            session.status = "failed"
            session.error = f"Sandbox session unavailable: {exc}"
            session.updated_at = _now_utc()
            logger.debug("view_shell_session failed for %s: %s", session.id, exc)
            return session.error
        output = view.get("output") or ""
        now = _now_utc()
        session.updated_at = now
        if touch:
            session.expires_at = now + timedelta(seconds=self._idle_timeout_seconds)
        exit_code = view.get("exit_code")
        if isinstance(exit_code, int):
            session.exit_code = exit_code
        if session.port == 0:
            detected_port = _detect_port(output)
            if detected_port is not None:
                session.port = detected_port

        shell_status = str(view.get("status") or "")
        if shell_status == "running":
            session.status = "running" if await self._probe_session(session, sandbox) else "starting"
            session.error = None
        elif shell_status == "completed":
            session.status = "stopped" if session.exit_code in (None, 0) else "failed"
            session.error = None if session.status == "stopped" else output[-4000:] or "Preview process exited with an error"
        elif shell_status == "terminated":
            session.status = "stopped"
            session.error = None
        else:
            session.status = "failed"
            session.error = output[-4000:] or f"Preview process ended with status {shell_status}"

        return output

    async def _probe_session(self, session: _PreviewSessionRecord, sandbox: AioSandbox) -> bool:
        if session.port == 0:
            return False
        try:
            result = await asyncio.to_thread(
                sandbox.fetch_local_url,
                port=session.port,
                path="/",
                method="GET",
                headers={"accept": "text/html,*/*"},
                body=None,
                timeout=10,
            )
        except Exception:
            return False
        return int(result["status"]) < 500

    async def _get_or_create_sandbox(self, *, thread_id: str) -> tuple[str, AioSandbox]:
        return await asyncio.to_thread(self._get_or_create_sandbox_sync, thread_id)

    def _get_or_create_sandbox_sync(self, thread_id: str) -> tuple[str, AioSandbox]:
        provider = get_sandbox_provider()
        if not isinstance(provider, AioSandboxProvider):
            raise HTTPException(status_code=501, detail="Preview sessions currently require the AIO sandbox provider")
        sandbox_id = provider.acquire(thread_id)
        sandbox = provider.get(sandbox_id)
        if not isinstance(sandbox, AioSandbox):
            raise HTTPException(status_code=500, detail="Failed to acquire AIO sandbox")
        return sandbox_id, sandbox

    async def _get_sandbox_for_existing_session(self, session: _PreviewSessionRecord) -> AioSandbox:
        return await asyncio.to_thread(self._get_sandbox_for_existing_session_sync, session)

    def _get_sandbox_for_existing_session_sync(self, session: _PreviewSessionRecord) -> AioSandbox:
        provider = get_sandbox_provider()
        if not isinstance(provider, AioSandboxProvider):
            raise HTTPException(status_code=501, detail="Preview sessions currently require the AIO sandbox provider")
        # Use acquire() so the sandbox is reclaimed from the warm pool if the agent
        # released it after its last run — get() alone would return None and falsely
        # report the sandbox as gone.
        try:
            acquired_id = provider.acquire(session.thread_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Preview sandbox is no longer available") from exc
        if acquired_id != session.sandbox_id:
            session.sandbox_id = acquired_id
        sandbox = provider.get(acquired_id)
        if not isinstance(sandbox, AioSandbox):
            raise HTTPException(status_code=404, detail="Preview sandbox is no longer available")
        return sandbox
