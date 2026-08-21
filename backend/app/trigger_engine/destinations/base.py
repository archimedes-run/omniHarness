"""Output destinations (FR-019, FR-020, FR-021).

A port with two implementations here. The local spoken destination registers
against this same port in the voice feature — the abstraction must exist now,
the voice implementation must not be required.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..models import Destination


class OutputDestination(ABC):
    kind: Destination

    @abstractmethod
    def deliver(self, text: str) -> None: ...


@dataclass
class QuietDestination(OutputDestination):
    """Records without delivering. Not a null object — a real destination that
    a rule may legitimately choose, and the one tests assert against."""

    kind: Destination = Destination.QUIET
    delivered: list[str] = field(default_factory=list)

    def deliver(self, text: str) -> None:
        self.delivered.append(text)


@dataclass
class RemoteDestination(OutputDestination):
    """Telegram. `send` is injected so tests need no network."""

    send: object = None
    kind: Destination = Destination.REMOTE
    delivered: list[str] = field(default_factory=list)

    def deliver(self, text: str) -> None:
        if self.send is not None:
            self.send(text)
        self.delivered.append(text)


@dataclass
class DestinationRegistry:
    """Resolves a rule's declared destination to a concrete one.

    `auto` resolves to local when the user is present and remote otherwise. With
    no local destination registered it resolves to remote (FR-021) — stated as
    behaviour rather than left to fall through a lookup miss.
    """

    remote: OutputDestination
    quiet: OutputDestination
    local: OutputDestination | None = None

    def resolve(self, declared: Destination, *, present: bool) -> OutputDestination:
        if declared is Destination.QUIET:
            return self.quiet
        if declared is Destination.REMOTE:
            return self.remote
        if declared is Destination.LOCAL:
            return self.local or self.remote
        # AUTO
        if present and self.local is not None:
            return self.local
        return self.remote
