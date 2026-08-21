"""The trigger-source interface (FR-002).

A source turns something that happened into a TriggerEvent. Each source owns
the mapping from its own domain onto `fingerprint_inputs`, because that
enumeration is per-type and is the requirement (FR-017b) rather than a detail.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import Rule, TriggerEvent


class TriggerSource(ABC):
    @abstractmethod
    def poll(self, rule: Rule, now: datetime) -> list[TriggerEvent]:
        """Events for this rule that have occurred and not yet been handled."""


class SourceUnavailable(RuntimeError):
    """The source could not be reached.

    Deliberately distinct from "no events". FR-029: an unreachable source is an
    UNOBSERVABLE condition, and reporting it as an absence of events is the
    Article X failure this exception exists to make impossible to express
    accidentally.
    """
