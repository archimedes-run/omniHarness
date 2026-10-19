"""Abstract base class for IM channels."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Any

from session_watcher.redaction import Channel as RedactionLevel
from session_watcher.redaction import redact_or_suppress

from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)

#: Sent in place of a message whose redaction failed. Says that something was
#: withheld and where to read it, and nothing of what it was.
WITHHELD_NOTICE = "A message was withheld: it could not be checked for credentials before leaving this machine, so it was not sent here. Open the conversation in OmniHarness to read it."


class Channel(ABC):
    """Base class for all IM channel implementations.

    Each channel connects to an external messaging platform and:
    1. Receives messages, wraps them as InboundMessage, publishes to the bus.
    2. Subscribes to outbound messages and sends replies back to the platform.

    Subclasses must implement ``start``, ``stop``, and ``send``.
    """

    def __init__(self, name: str, bus: MessageBus, config: dict[str, Any]) -> None:
        self.name = name
        self.bus = bus
        self.config = config
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    # -- lifecycle ---------------------------------------------------------

    @abstractmethod
    async def start(self) -> None:
        """Start listening for messages from the external platform."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the channel."""

    # -- outbound ----------------------------------------------------------

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message back to the external platform.

        The implementation should use ``msg.chat_id`` and ``msg.thread_ts``
        to route the reply to the correct conversation/thread.
        """

    async def deliver(self, msg: OutboundMessage) -> bool:
        """THE way a message leaves through this channel. Redacts, then sends.

        Returns True when the message's content was sent, False when it was
        withheld. Raises whatever `send` raises, so a caller that must know
        whether delivery happened — the trigger engine — finds out.

        Every outbound message passes here: chat replies via `_on_outbound`,
        proactive messages via the trigger engine's remote destination. Before
        this existed `app/channels/` redacted nothing, and an agent reply quoting
        a .env went to Telegram verbatim (audit P-4). A gate test keeps this the
        only caller of `send`.

        FAILS CLOSED. If redaction raises, the content is not sent — a fixed
        notice goes instead, and the caller skips the attachments.

        The pattern set, not the REMOTE level: REMOTE also replaces code fences
        with "[code]" and shortens paths, which suits an unbidden session
        summary and would wreck a coding answer the user asked for. Proactive
        messages still get REMOTE, upstream in the trigger engine's Releaser.
        Patterns catch RECOGNISED secret shapes only; that limit is the
        redactor's, and is stated there.
        """
        safe, ok = redact_or_suppress(msg.text, RedactionLevel.LOCAL)
        if not ok:
            logger.error("[%s] redaction failed; withholding a message to chat %s", self.name, msg.chat_id)
            await self.send(replace(msg, text=WITHHELD_NOTICE, attachments=[], artifacts=[]))
            return False
        await self.send(msg if safe == msg.text else replace(msg, text=safe))
        return True

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        """Upload a single file attachment to the platform.

        Returns True if the upload succeeded, False otherwise.
        Default implementation returns False (no file upload support).
        """
        return False

    # -- helpers -----------------------------------------------------------

    def _make_inbound(
        self,
        chat_id: str,
        user_id: str,
        text: str,
        *,
        msg_type: InboundMessageType = InboundMessageType.CHAT,
        thread_ts: str | None = None,
        files: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> InboundMessage:
        """Convenience factory for creating InboundMessage instances."""
        return InboundMessage(
            channel_name=self.name,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            msg_type=msg_type,
            thread_ts=thread_ts,
            files=files or [],
            metadata=metadata or {},
        )

    async def _on_outbound(self, msg: OutboundMessage) -> None:
        """Outbound callback registered with the bus.

        Only forwards messages targeted at this channel.
        Sends the text message first, then uploads any file attachments.
        File uploads are skipped entirely when the text send fails to avoid
        partial deliveries (files without accompanying text).
        """
        if msg.channel_name == self.name:
            try:
                sent = await self.deliver(msg)
            except Exception:
                logger.exception("Failed to send outbound message on channel %s", self.name)
                return  # Do not attempt file uploads when the text message failed
            if not sent:
                return  # withheld: its attachments are withheld with it

            for attachment in msg.attachments:
                try:
                    success = await self.send_file(msg, attachment)
                    if not success:
                        logger.warning("[%s] file upload skipped for %s", self.name, attachment.filename)
                except Exception:
                    logger.exception("[%s] failed to upload file %s", self.name, attachment.filename)

    async def receive_file(self, msg: InboundMessage, thread_id: str) -> InboundMessage:
        """
        Optionally process and materialize inbound file attachments for this channel.

        By default, this method does nothing and simply returns the original message.
        Subclasses (e.g. FeishuChannel) may override this to download files (images, documents, etc)
        referenced in msg.files, save them to the sandbox, and update msg.text to include
        the sandbox file paths for downstream model consumption.

        Args:
            msg: The inbound message, possibly containing file metadata in msg.files.
            thread_id: The resolved OmniHarness thread ID for sandbox path context.

        Returns:
            The (possibly modified) InboundMessage, with text and/or files updated as needed.
        """
        return msg
