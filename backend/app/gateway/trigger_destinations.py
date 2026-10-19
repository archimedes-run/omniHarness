"""The trigger engine's remote destination: an IM channel (FR-019).

Gateway-side, because it reaches the channel service. The engine knows only the
`OutputDestination` port; this is the one production implementation of its
remote slot, which until now held a QuietDestination: every `remote` and
`auto` delivery landed in an in-memory list (audit T-2).

Delivery goes through `Channel.deliver`, the boundary that redacts every
message leaving through a channel, and fails closed. The engine's Releaser has
already redacted at the stricter REMOTE level; this is the second, independent
check, at the place where text actually leaves the process.

Every way delivery can fail RAISES, with a reason a person can act on. The
Releaser records it on the firing as FAILED. Nothing here returns quietly
without sending: a delivery that reports success without sending is the same
defect as the stub it replaces.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app.trigger_engine.destinations.base import OutputDestination
from app.trigger_engine.models import Destination

logger = logging.getLogger(__name__)

#: Bounds one delivery, including the channel client's own retries
#: (Telegram: 3 attempts, 1 s and 2 s apart).
DELIVERY_TIMEOUT_SECONDS = 60.0


class DeliveryFailed(RuntimeError):
    """The message did not reach the user. The message says why."""


@dataclass
class UnconfiguredRemote(OutputDestination):
    """The remote slot when no recipient is configured. Fails every delivery,
    naming the setting, rather than guessing whom to message."""

    kind: Destination = Destination.REMOTE

    def deliver(self, text: str) -> None:
        raise DeliveryFailed("no remote recipient is configured; set trigger_engine.remote.channel and trigger_engine.remote.chat_id in config.yaml")


@dataclass
class ChannelDestination(OutputDestination):
    """Delivers to one chat on one IM channel, through the channel boundary.

    Called from the engine's worker thread; the channel's client belongs to the
    gateway's event loop, so the send is scheduled there and awaited here.
    """

    channel: str
    chat_id: str
    main_loop: asyncio.AbstractEventLoop
    kind: Destination = Destination.REMOTE
    delivered: list[str] = field(default_factory=list)

    def deliver(self, text: str) -> None:
        from app.channels.message_bus import OutboundMessage
        from app.channels.service import get_channel_service

        service = get_channel_service()
        if service is None:
            raise DeliveryFailed("the IM channel service is not running")
        channel = service.get_channel(self.channel)
        if channel is None or not channel.is_running:
            raise DeliveryFailed(f"channel {self.channel!r} is not running; enable it under channels.{self.channel} in config.yaml, with its credentials")

        msg = OutboundMessage(channel_name=self.channel, chat_id=self.chat_id, thread_id="", text=text, metadata={"source": "trigger-engine"})
        future = asyncio.run_coroutine_threadsafe(channel.deliver(msg), self.main_loop)
        try:
            sent = future.result(timeout=DELIVERY_TIMEOUT_SECONDS)
        except Exception as exc:
            future.cancel()
            raise DeliveryFailed(f"{self.channel} did not accept the message: {type(exc).__name__}: {exc}") from exc
        if not sent:
            raise DeliveryFailed(f"withheld at the {self.channel} boundary: the message could not be checked for credentials, so only a notice was sent")
        self.delivered.append(text)
