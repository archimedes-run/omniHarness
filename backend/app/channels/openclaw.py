"""OpenClaw channel — bridges the OpenClaw AI gateway to OmniHarness via webhooks.

OpenClaw (github.com/openclaw/openclaw) is a Node.js personal AI assistant
gateway. It sends messages to OmniHarness via HTTP webhook and receives
responses back via a configurable outbound URL.

Auth model: Authorization: Bearer <token> header on incoming requests.
Payload schema (OpenClaw /hooks/agent): {message, agentId, channel, to, ...}

Configuration keys (``config.yaml`` under ``channels.openclaw``):
    - ``bearer_token``: Token to validate incoming requests (leave empty to
      disable auth checking in dev/trusted environments).
    - ``openclaw_url``: Base URL of the OpenClaw instance for outbound replies
      (e.g. ``http://openclaw:3001``). Leave empty to suppress reply attempts.
"""

from __future__ import annotations

import logging
from typing import Any

from app.channels.base import Channel
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus, OutboundMessage

logger = logging.getLogger(__name__)


class OpenClawChannel(Channel):
    """OpenClaw webhook channel.

    Incoming messages arrive via ``POST /api/channels/openclaw/webhook``
    (handled by ``app.gateway.routers.openclaw_webhook``).
    Outbound replies are sent to OpenClaw's ``/hooks/outbound`` endpoint when
    ``openclaw_url`` is configured.
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__("openclaw", bus, config)
        self._bearer_token: str = config.get("bearer_token", "")
        self._openclaw_url: str = config.get("openclaw_url", "").rstrip("/")

    async def start(self) -> None:
        if self._running:
            return
        self.bus.subscribe_outbound(self._on_outbound)
        self._running = True
        logger.info(
            "OpenClaw channel started — webhook: POST /api/channels/openclaw/webhook, "
            "outbound_url=%s",
            self._openclaw_url or "(not configured)",
        )

    async def stop(self) -> None:
        if not self._running:
            return
        self.bus.unsubscribe_outbound(self._on_outbound)
        self._running = False
        logger.info("OpenClaw channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a reply back to OpenClaw if ``openclaw_url`` is configured."""
        if not self._openclaw_url:
            logger.debug(
                "openclaw_url not configured — suppressing outbound reply for chat_id=%s",
                msg.chat_id,
            )
            return

        try:
            import httpx
        except ImportError:
            logger.error("httpx is not installed; cannot send reply to OpenClaw")
            return

        headers: dict[str, str] = {}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"

        payload = {
            "message": msg.text,
            "channel": "omniharness",
            "to": msg.chat_id,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._openclaw_url}/hooks/outbound",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                logger.debug("OpenClaw outbound reply sent for chat_id=%s", msg.chat_id)
        except Exception:
            logger.exception("Failed to send reply to OpenClaw for chat_id=%s", msg.chat_id)

    def verify_bearer_token(self, token: str) -> bool:
        """Return True if *token* matches the configured bearer token.

        When no token is configured every request is accepted (dev/trusted
        network mode).
        """
        if not self._bearer_token:
            return True
        return token == self._bearer_token

    async def handle_webhook(self, payload: dict[str, Any]) -> None:
        """Route an inbound OpenClaw webhook payload to the agent dispatcher.

        Maps OpenClaw's documented payload fields:
            {message, agentId, channel, to, timeoutSeconds, ...}
        """
        message = str(payload.get("message", "")).strip()
        if not message:
            logger.warning("OpenClaw webhook received empty message payload; ignoring")
            return

        agent_id = str(payload.get("agentId", ""))
        to = str(payload.get("to", ""))

        # Prefer the explicit ``to`` field for the chat identifier so that
        # different OpenClaw agents can each have isolated OmniHarness threads.
        chat_id = to or agent_id or "openclaw"
        user_id = agent_id or "openclaw"

        inbound = InboundMessage(
            channel_name=self.name,
            chat_id=chat_id,
            user_id=user_id,
            text=message,
            msg_type=InboundMessageType.CHAT,
        )
        await self.bus.publish_inbound(inbound)
        logger.debug("OpenClaw inbound enqueued: chat_id=%s, user_id=%s", chat_id, user_id)
