"""App-layer implementation of the PreviewController port.

``GatewayPreviewController`` wraps ``PreviewSessionManager`` and the
filesystem manifest scanner so harness tools and middleware can request
previews without importing from ``app.*``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from omniharness.config.paths import get_paths
from omniharness.preview.preview_controller import PreviewStatusSummary

if TYPE_CHECKING:
    from app.gateway.preview_sessions import PreviewSessionManager

logger = logging.getLogger(__name__)

_MANIFEST_FILENAME = "artifact_manifest.json"
_SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "dist",
        ".next",
        "build",
    }
)


def _iter_manifest_paths(root: Path):
    """Walk *root* yielding ``artifact_manifest.json`` paths, skipping heavy dirs."""
    if not root.exists():
        return
    for path in root.rglob(_MANIFEST_FILENAME):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        yield path


def _find_first_web_app_manifest(thread_id: str, user_id: str) -> dict | None:
    """Return the raw dict of the first valid ``web_app`` manifest, or ``None``."""
    outputs_dir = get_paths().sandbox_outputs_dir(thread_id, user_id=user_id).resolve()
    for manifest_path in _iter_manifest_paths(outputs_dir):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "web_app":
            continue
        artifact_id = data.get("id")
        if not artifact_id:
            continue
        preview = data.get("preview") or {}
        if not preview.get("command"):
            continue
        # Normalise source_path when absent
        if not data.get("source_path"):
            data = {**data, "source_path": f"/mnt/user-data/workspace/{artifact_id}"}
        return data
    return None


class GatewayPreviewController:
    """Implements ``PreviewController`` using the Gateway's ``PreviewSessionManager``."""

    def __init__(self, manager: PreviewSessionManager) -> None:
        self._manager = manager

    # ------------------------------------------------------------------
    # PreviewController protocol
    # ------------------------------------------------------------------

    async def get_status(self, *, thread_id: str, user_id: str) -> PreviewStatusSummary:
        has_web_app = _find_first_web_app_manifest(thread_id, user_id) is not None
        try:
            sessions = await self._manager.list_sessions(user_id=user_id, thread_id=thread_id)
        except Exception:
            sessions = []

        if not sessions:
            return PreviewStatusSummary(
                has_web_app=has_web_app,
                session_status="not_started",
            )

        # Prefer the most-recent active session, fall back to the newest overall.
        active_response = next(
            (s for s in sessions if s.status in ("running", "starting")),
            sessions[0],
        )

        # Pull client_errors from the underlying record (not exposed via response).
        session_record = self._manager._sessions.get(active_response.id)
        client_errors: list[str] = []
        if session_record is not None:
            for err in getattr(session_record, "client_errors", []):
                if isinstance(err, dict):
                    client_errors.append(err.get("message") or str(err))
                else:
                    client_errors.append(str(err))

        return PreviewStatusSummary(
            has_web_app=has_web_app,
            session_status=active_response.status,
            client_errors=client_errors,
            session_error=active_response.error,
        )

    async def request_preview(self, *, thread_id: str, user_id: str) -> None:
        manifest = _find_first_web_app_manifest(thread_id, user_id)
        if manifest is None:
            logger.debug("No web_app manifest found for thread %s; skipping auto-start", thread_id)
            return

        from app.gateway.preview_sessions import PreviewSessionCreateRequest

        preview = manifest.get("preview") or {}
        body = PreviewSessionCreateRequest(
            artifact_id=manifest["id"],
            root_path=manifest["source_path"],
            command=preview["command"],
            port=preview.get("port"),
        )
        try:
            await self._manager.create_session_from_manifest(
                user_id=user_id,
                thread_id=thread_id,
                body=body,
            )
            logger.debug("Auto-started preview for thread %s artifact %s", thread_id, manifest["id"])
        except Exception:
            logger.debug("Auto-start preview failed for thread %s (non-fatal)", thread_id, exc_info=True)
