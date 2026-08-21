"""Opt-in model summarizer: load -> summarize -> release (Gate 2, FR-008a).

Article VI caps the daemon at under 500 MB idle. A resident model blows that on
its own, and does it invisibly — the feature works perfectly while violating the
constitution. So the handle lives inside a context manager scoped to one batch
and is never stored on the instance.

The weakref test in test_summarizer_lifecycle.py exists to prove that claim, and
Gate 2's verification proves the test can actually fail.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from ..models import SummaryProvenance
from .mechanical import MechanicalSummarizer
from .port import SummarizerPort, Summary


class ModelUnavailable(RuntimeError):
    """The configured model could not be loaded for this batch."""


@dataclass
class OnDemandModelSummarizer(SummarizerPort):
    """Loads a model per batch and releases it before returning.

    `loader` returns an object exposing `summarize(list[str]) -> list[str]`. It is
    called per batch, never cached — caching it is precisely the regression Gate 2
    watches for.
    """

    loader: Callable[[], object]
    fallback: SummarizerPort | None = None

    @contextmanager
    def _model(self) -> Iterator[object]:
        model = self.loader()
        try:
            yield model
        finally:
            # Drop the only strong reference we hold. Nothing else in this class
            # may retain one — no self._model, no module-level cache.
            del model

    def summarize(self, texts: list[str]) -> list[Summary]:
        if not texts:
            return []
        try:
            with self._model() as model:
                out = list(model.summarize(texts))
        except Exception as exc:  # noqa: BLE001 - any loader failure degrades, never crashes
            fb = self.fallback or MechanicalSummarizer()
            if fb is None:
                raise ModelUnavailable(str(exc)) from exc
            return fb.summarize(texts)
        if len(out) != len(texts):
            return (self.fallback or MechanicalSummarizer()).summarize(texts)
        return [Summary(text=t, provenance=SummaryProvenance.MODEL) for t in out]
