"""Webhook receiver for inbound OpenClaw → OmniHarness messages.

Mounted at POST /api/channels/openclaw/webhook.
The ``OpenClawChannel`` must be active (enabled in config.yaml) for this
endpoint to accept requests.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/channels/openclaw", tags=["channels"])


@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def receive_openclaw_webhook(
    request: Request,
    payload: dict[str, Any],
) -> dict[str, str]:
    """Accept an inbound message from OpenClaw and hand it to the agent.

    OpenClaw sends ``Authorization: Bearer <token>`` headers for auth.
    The token must match ``channels.openclaw.bearer_token`` in config.yaml
    (or auth is skipped when the token is left empty).
    """
    from app.channels.service import get_channel_service

    service = get_channel_service()
    if service is None:
        raise HTTPException(status_code=503, detail="Channel service is not running")

    channel = service.get_channel("openclaw")
    if channel is None:
        raise HTTPException(
            status_code=404,
            detail="OpenClaw channel is not active — set channels.openclaw.enabled: true in config.yaml",
        )

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not channel.verify_bearer_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")

    await channel.handle_webhook(payload)
    return {"status": "accepted"}
