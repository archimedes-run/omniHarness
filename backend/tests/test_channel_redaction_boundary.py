"""Every message leaving through an IM channel is redacted, fail-closed (audit P-4).

Before this, `app/channels/` had no redaction at all: an agent reply quoting a
.env file went to Telegram verbatim. The trigger engine redacted its own
proactive messages, but chat replies — the bulk of channel traffic — passed
straight from the bus to the platform client.

The boundary is `Channel.deliver`, called by the bus path (`_on_outbound`) and by
the trigger engine's remote destination. A gate below keeps it the only caller
of a channel's `send`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.channels.base import WITHHELD_NOTICE, Channel
from app.channels.message_bus import MessageBus, OutboundMessage, ResolvedAttachment

SECRET = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"
APP = Path(__file__).resolve().parents[1] / "app"


class _Recording(Channel):
    """A channel with its network client removed; the base class is real."""

    def __init__(self, bus: MessageBus) -> None:
        super().__init__(name="telegram", bus=bus, config={})
        self.sent: list[OutboundMessage] = []
        self.files: list[str] = []

    async def start(self) -> None:
        self.bus.subscribe_outbound(self._on_outbound)

    async def stop(self) -> None:
        self.bus.unsubscribe_outbound(self._on_outbound)

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        self.files.append(attachment.filename)
        return True


def _reply(text: str, attachments=()) -> OutboundMessage:
    return OutboundMessage(channel_name="telegram", chat_id="4242", thread_id="t1", text=text, attachments=list(attachments))


def _attachment(tmp_path) -> ResolvedAttachment:
    f = tmp_path / "report.md"
    f.write_text("report")
    return ResolvedAttachment(virtual_path="/mnt/user-data/outputs/report.md", actual_path=f, filename="report.md", mime_type="text/markdown", size=6, is_image=False)


@pytest.mark.asyncio
async def test_a_reply_on_the_bus_is_redacted_before_it_reaches_the_platform() -> None:
    bus = MessageBus()
    channel = _Recording(bus)
    await channel.start()

    await bus.publish_outbound(_reply(f"Your token is {SECRET}, keep it safe."))

    [sent] = channel.sent
    assert SECRET not in sent.text
    assert "[redacted]" in sent.text  # positive control: the redactor ran and said so


@pytest.mark.asyncio
async def test_code_in_a_reply_the_user_asked_for_survives() -> None:
    """The boundary removes secret-shaped text, not code. The REMOTE level's
    code-fence stripping is for unbidden summaries, and stays upstream there."""
    bus = MessageBus()
    channel = _Recording(bus)
    await channel.start()

    await bus.publish_outbound(_reply("Run this:\n```bash\nmake test\n```"))

    assert "make test" in channel.sent[0].text


@pytest.mark.asyncio
async def test_when_redaction_fails_nothing_of_the_reply_is_sent(tmp_path, monkeypatch) -> None:
    """Fail closed: a notice instead of the content, and no attachments."""
    import session_watcher.redaction as redaction

    def _broken(text):
        raise ValueError("pattern engine exploded")

    monkeypatch.setattr(redaction, "_apply_patterns", _broken)
    bus = MessageBus()
    channel = _Recording(bus)
    await channel.start()

    await bus.publish_outbound(_reply(f"Your token is {SECRET}", attachments=[_attachment(tmp_path)]))

    [sent] = channel.sent
    assert sent.text == WITHHELD_NOTICE
    assert SECRET not in sent.text
    assert channel.files == [], "attachments went out with a reply that was withheld"


@pytest.mark.asyncio
async def test_attachments_still_follow_a_reply_that_was_sent(tmp_path) -> None:
    """Positive control for the attachment rule above."""
    bus = MessageBus()
    channel = _Recording(bus)
    await channel.start()

    await bus.publish_outbound(_reply("Here is the report.", attachments=[_attachment(tmp_path)]))

    assert channel.files == ["report.md"]


def _self_send_calls() -> list[str]:
    """Every `self.send(...)` inside a Channel class in app/, as file:Class.method."""
    found = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            is_channel = cls.name == "Channel" and path.name == "base.py" and path.parent.name == "channels"
            if not is_channel and not any(isinstance(b, ast.Name) and b.id == "Channel" for b in cls.bases):
                continue
            for fn in ast.walk(cls):
                if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "send" and isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
                        found.append(f"{path.relative_to(APP)}:{cls.name}.{fn.name}")
    return found


def test_deliver_is_the_only_caller_of_a_channels_send() -> None:
    """The gate. A second caller of `send` is a second, unredacted way out."""
    calls = _self_send_calls()

    assert "channels/base.py:Channel.deliver" in calls, "positive control: the scan finds the one legitimate call"
    others = [c for c in calls if c != "channels/base.py:Channel.deliver"]
    assert not others, f"a channel's send() is called outside Channel.deliver, bypassing redaction: {others}"
