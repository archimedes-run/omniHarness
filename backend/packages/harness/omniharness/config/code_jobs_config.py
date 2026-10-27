"""Coding jobs (spec 009, Slice 1): OpenCode as the worker in the container sandbox.

Offered only with the hardened container sandbox (the same conditions as
`bash`, app/policy/runtime_floors.py) and only when the lead's model can be
served through the gateway's LLM proxy. Every number here is a ceiling the
gateway enforces, never a hint to the worker.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelPrice(BaseModel):
    """US dollars per million tokens."""

    input: float = Field(ge=0)
    cached_input: float | None = Field(default=None, ge=0)
    output: float = Field(ge=0)


class CodeJobsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, description="Offer code_job when the hardened container sandbox is configured")
    model: str | None = Field(default=None, description="Model (a name under `models:`) the worker uses; default: the lead's model (D2)")
    budget_usd: float = Field(default=1.0, gt=0, le=50, description="Per-job model spend ceiling (D2: $1)")
    monthly_cap_usd: float = Field(default=20.0, gt=0, le=10_000, description="All jobs in a calendar month (UTC); reached = new jobs refused")
    wall_seconds: int = Field(default=1800, ge=60, le=4 * 3600, description="A job is stopped after this long")
    verify_timeout_seconds: int = Field(default=600, ge=30, le=600, description="Hard cap on the gateway's verification command (D4)")
    rate_per_minute: int = Field(default=60, ge=1, le=600, description="Model calls per sandbox per minute through the proxy")
    max_concurrent_calls: int = Field(default=3, ge=1, le=8, description="Model calls one job may have in flight at once")
    max_request_bytes: int = Field(default=8 * 1024 * 1024, ge=64 * 1024, le=64 * 1024 * 1024)
    proxy_port: int = Field(default=8790, ge=1024, le=65535, description="The LLM proxy's port on the sandbox network")
    proxy_bind: str | None = Field(default=None, description="The LLM proxy's address; default: the gateway's own address on the sandbox network")
    prices: dict[str, ModelPrice] = Field(default_factory=dict, description="Per-model prices overriding the built-in table")
