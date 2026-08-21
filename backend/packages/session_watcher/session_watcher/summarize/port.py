"""The summarizer boundary (FR-008, FR-008c).

Two implementations, and which one is the DEFAULT matters: MechanicalSummarizer
is what a fresh install uses. That is not a fallback for a broken model — it is
the ordinary case, and it has to produce lines a person would accept reading.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import SummaryProvenance


@dataclass(frozen=True)
class Summary:
    text: str
    provenance: SummaryProvenance


class SummarizerPort(ABC):
    @abstractmethod
    def summarize(self, texts: list[str]) -> list[Summary]:
        """Summarize a batch. One Summary per input, order preserved."""
