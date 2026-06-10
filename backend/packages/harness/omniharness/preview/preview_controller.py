"""PreviewController port: harness-layer protocol for live-preview operations.

This module provides:
- ``PreviewStatusSummary`` – a simple dataclass capturing the current preview
  state for a thread (session status, client errors, whether a web app artifact
  was detected).
- ``PreviewController`` – a ``Protocol`` that the app layer implements via
  ``GatewayPreviewController`` (``app.gateway.preview_controller_adapter``).
  The harness layer (tools, middleware) only imports from here so the
  harness → app import boundary is never crossed.
- Module-level singleton accessors mirroring the ``sandbox_provider`` pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


@dataclass
class PreviewStatusSummary:
    """Snapshot of the preview state for a single thread."""

    has_web_app: bool
    """True when at least one ``web_app`` artifact manifest exists for this thread."""

    session_status: Literal["not_started", "starting", "running", "failed", "stopped"]
    """Status of the most-recent active preview session, or ``"not_started"``."""

    client_errors: list[str] = field(default_factory=list)
    """Client-side JS errors captured by the preview shim."""

    session_error: str | None = None
    """Server-side error from the preview session, if any."""


@runtime_checkable
class PreviewController(Protocol):
    """Protocol that the app layer implements to give harness tools/middleware
    access to live-preview operations without a reverse import."""

    async def get_status(self, *, thread_id: str, user_id: str) -> PreviewStatusSummary:
        """Return the current preview state for *thread_id*."""
        ...

    async def request_preview(self, *, thread_id: str, user_id: str) -> None:
        """Auto-detect the first ``web_app`` manifest and start (or no-op) a preview.

        Non-raising: implementations log failures at DEBUG level.
        """
        ...


# ---------------------------------------------------------------------------
# Module-level singleton (mirrors sandbox_provider.py pattern)
# ---------------------------------------------------------------------------

_default_controller: PreviewController | None = None


def get_preview_controller() -> PreviewController | None:
    """Return the active ``PreviewController``, or ``None`` if not configured."""
    return _default_controller


def set_preview_controller(controller: PreviewController) -> None:
    """Register the active ``PreviewController`` (called from app lifespan)."""
    global _default_controller
    _default_controller = controller


def reset_preview_controller() -> None:
    """Clear the registered controller (used in tests)."""
    global _default_controller
    _default_controller = None
