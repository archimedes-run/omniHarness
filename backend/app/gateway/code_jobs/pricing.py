"""Model prices for coding-job budgets (estimates, US dollars per million tokens).

Published list prices at the time of writing; `code_jobs.prices` in
config.yaml overrides any of them. A model not in the table is charged at
FALLBACK, the dearest row, so an unknown model can only make the budget end
sooner, never later.
"""

from __future__ import annotations

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


def price_for(model: str, overrides: dict[str, ModelPrice] | None = None) -> ModelPrice:
    name = (model or "").strip().lower()
    for table in (overrides or {}, TABLE):
        if name in table:
            return table[name]
    # Dated or suffixed ids ("gpt-5-2025-08-07", "claude-sonnet-4-5-20250929"):
    # the longest table key the id starts with.
    for table in (overrides or {}, TABLE):
        keys = sorted((k for k in table if name.startswith(k.lower())), key=len, reverse=True)
        if keys:
            return table[keys[0]]
    return FALLBACK


def cost_usd(model: str, *, input_tokens: int, cached_tokens: int, output_tokens: int, overrides: dict[str, ModelPrice] | None = None) -> float:
    p = price_for(model, overrides)
    cached = max(0, min(cached_tokens, input_tokens))
    fresh = max(0, input_tokens - cached)
    cached_rate = p.cached_input if p.cached_input is not None else p.input
    return (fresh * p.input + cached * cached_rate + max(0, output_tokens) * p.output) / 1_000_000
