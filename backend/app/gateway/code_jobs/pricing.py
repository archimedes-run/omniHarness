"""Model prices for coding-job budgets (estimates, US dollars per million tokens).

Published list prices at the time of writing; `code_jobs.prices` in
config.yaml overrides any of them. A model not in the table is charged at
FALLBACK, the dearest row, so an unknown model can only make the budget end
sooner, never later.
"""

from __future__ import annotations

import re

from omniharness.config.code_jobs_config import ModelPrice

TABLE: dict[str, ModelPrice] = {
    "gpt-5": ModelPrice(input=1.25, cached_input=0.125, output=10.0),
    "gpt-5-mini": ModelPrice(input=0.25, cached_input=0.025, output=2.0),
    "gpt-5-nano": ModelPrice(input=0.05, cached_input=0.005, output=0.4),
    "gpt-4.1": ModelPrice(input=2.0, cached_input=0.5, output=8.0),
    "gpt-4.1-mini": ModelPrice(input=0.4, cached_input=0.1, output=1.6),
    "gpt-4o": ModelPrice(input=2.5, cached_input=1.25, output=10.0),
    "gpt-4o-mini": ModelPrice(input=0.15, cached_input=0.075, output=0.6),
    "claude-opus-4": ModelPrice(input=15.0, cached_input=1.5, output=75.0),
    "claude-sonnet-4": ModelPrice(input=3.0, cached_input=0.3, output=15.0),
    "claude-haiku-4": ModelPrice(input=1.0, cached_input=0.1, output=5.0),
    "deepseek-chat": ModelPrice(input=0.27, cached_input=0.07, output=1.1),
}
FALLBACK = ModelPrice(input=15.0, cached_input=15.0, output=75.0)


#: The only suffix a table key may be followed by and still match: a date
#: ("-2025-08-07", "-20250807"). Any other suffix is a different model
#: ("gpt-5.1", "gpt-5-pro") and is charged at FALLBACK.
_DATED = re.compile(r"^-(\d{4}-\d{2}-\d{2}|\d{8})$")


def price_for(model: str, overrides: dict[str, ModelPrice] | None = None) -> ModelPrice:
    name = (model or "").strip().lower()
    for table in (overrides or {}, TABLE):
        lowered = {k.lower(): v for k, v in table.items()}
        if name in lowered:
            return lowered[name]
        # A dated id of a table model ("gpt-5-mini-2025-08-07").
        for key, price in lowered.items():
            if name.startswith(key) and _DATED.match(name[len(key) :]):
                return price
    return FALLBACK


def cost_usd(model: str, *, input_tokens: int, cached_tokens: int, output_tokens: int, overrides: dict[str, ModelPrice] | None = None) -> float:
    p = price_for(model, overrides)
    cached = max(0, min(cached_tokens, input_tokens))
    fresh = max(0, input_tokens - cached)
    cached_rate = p.cached_input if p.cached_input is not None else p.input
    return (fresh * p.input + cached * cached_rate + max(0, output_tokens) * p.output) / 1_000_000
