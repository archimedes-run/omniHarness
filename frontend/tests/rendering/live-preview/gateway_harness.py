"""The REAL gateway side of the live preview, for live-preview.spec.ts.

Serves the gateway's previews router (the frame link mint and the frame link
route, unchanged) with the gateway's CSRF middleware, over one preview session
per fixture app (apps/<name>), each on a real local HTTP dev server. Only the
sandbox is stood in for: its fetch of the dev server is a plain local request.

    cd backend && PYTHONPATH=packages/harness:.:packages/session_watcher \\
      .venv/bin/python ../frontend/tests/rendering/live-preview/gateway_harness.py \\
      --port 8899 --thread <the spec's THREAD>

then run the spec with LIVE_PREVIEW_GATEWAY=http://127.0.0.1:8899.
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import threading
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("AUTH_JWT_SECRET", "live-preview-harness-secret-at-least-32-chars")

APPS = Path(__file__).resolve().parent / "apps"
OWNER = uuid.UUID("00000000-0000-4000-8000-0000000000aa")


def _dev_server(app: str) -> int:
    root = APPS / app

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("content-length") or 0))
            if self.path.split("?")[0] == "/api/echo":
                return self._send(200, body or b"{}", "application/json")
            return self._send(404, b"", "text/plain")

        def do_GET(self):
            path = self.path.split("?")[0]
            target = (root / path.lstrip("/")).resolve()
            if not str(target).startswith(str(root.resolve())):
                return self._send(404, b"", "text/plain")
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                if app == "vite-app" and "." not in path.rsplit("/", 1)[-1]:
                    target = root / "index.html"
                else:
                    return self._send(404, b"not found", "text/plain")
            ctype = "text/javascript" if path.startswith("/@vite/") else (mimetypes.guess_type(target.name)[0] or "text/plain")
            if ctype == "application/javascript":
                ctype = "text/javascript"
            return self._send(200, target.read_bytes(), ctype)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


class _LocalSandbox:
    """Stands in for the sandbox: its local fetch is a plain local request."""

    def fetch_local_url(self, *, port, path, method="GET", headers=None, body=None, timeout=30):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method, headers=headers or {})
        try:
            resp = urllib.request.build_opener(NoRedirect).open(req, timeout=timeout)
        except urllib.error.HTTPError as err:
            resp = err
        return {"status": resp.status if hasattr(resp, "status") else resp.code, "headers": {k.lower(): v for k, v in resp.headers.items()}, "body": resp.read()}


def build(thread: str):
    from fastapi import FastAPI, Request
    from starlette.middleware.base import BaseHTTPMiddleware

    from app.gateway.auth.models import User
    from app.gateway.authz import AuthContext, Permissions
    from app.gateway.csrf_middleware import CSRFMiddleware
    from app.gateway.preview_sessions import PreviewSessionManager, _PreviewSessionRecord
    from app.gateway.routers import previews

    manager = PreviewSessionManager(idle_timeout_seconds=3600)
    sandbox = _LocalSandbox()

    async def existing(session):
        return sandbox

    manager._get_sandbox_for_existing_session = existing  # type: ignore[method-assign]
    now = datetime.now(UTC)
    for app in ("vite-app", "site", "probe"):
        manager._sessions[f"preview_{app}"] = _PreviewSessionRecord(
            id=f"preview_{app}",
            user_id=str(OWNER),
            thread_id=thread,
            artifact_id=app,
            root_path=f"/mnt/user-data/workspace/{app}",
            command="npm run dev",
            port=_dev_server(app),
            sandbox_id="local",
            shell_session_id=f"preview_{app}",
            status="running",
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=1),
        )

    user = User(email="owner@example.com", password_hash="x", system_role="user", id=OWNER)

    class OwnerSession(BaseHTTPMiddleware):
        # The owner's session for the cookie routes (the mint). The frame link
        # route reads none of this: its token is checked against the preview.
        async def dispatch(self, request: Request, call_next):
            request.state.user = user
            request.state.auth = AuthContext(user=user, permissions=[Permissions.THREADS_READ, Permissions.THREADS_WRITE])
            return await call_next(request)

    from unittest.mock import AsyncMock, MagicMock

    fastapi_app = FastAPI()
    fastapi_app.add_middleware(OwnerSession)
    fastapi_app.add_middleware(CSRFMiddleware)
    store = MagicMock()
    store.check_access = AsyncMock(return_value=True)
    fastapi_app.state.thread_store = store
    fastapi_app.state.preview_session_manager = manager
    fastapi_app.include_router(previews.router)
    return fastapi_app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--thread", required=True)
    args = parser.parse_args()
    uvicorn.run(build(args.thread), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
