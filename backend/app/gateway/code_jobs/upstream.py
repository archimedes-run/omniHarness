"""Where the LLM proxy sends a coding job's model calls, and with which key.

The worker speaks the common chat-completions API to the proxy; the proxy
forwards to the provider of the model the job uses (the lead's by default,
D2), injecting the provider key server-side. The key is read here, in the
gateway, and never leaves it: it is not in the job, the token, the sandbox,
the store or any log line.

Supported: OpenAI-compatible chat models (`langchain_openai:ChatOpenAI` and
the patched OpenAI-family classes, with their own base_url) and Anthropic
models through Anthropic's OpenAI-compatible endpoint. Anything else is not
served, and code_job is not offered (FR-011, honest limits).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from omniharness.config.app_config import AppConfig

_OPENAI_FAMILY = (
    "langchain_openai:ChatOpenAI",
    "omniharness.models.patched_openai:",
    "omniharness.models.patched_deepseek:",
    "omniharness.models.vllm_provider:",
    "langchain_deepseek:",
)
_ANTHROPIC = ("langchain_anthropic:ChatAnthropic",)


@dataclass(frozen=True)
class Upstream:
    name: str  # the config model name
    model: str  # the provider's model id
    base_url: str  # ends with /v1 (or the provider's equivalent)
    api_key: str
    provider: str  # "openai" | "anthropic"

    def __repr__(self) -> str:  # never show the key
        return f"Upstream(name={self.name!r}, model={self.model!r}, base_url={self.base_url!r}, provider={self.provider!r})"

    @property
    def reasoning_model(self) -> bool:
        m = self.model.lower()
        return self.provider == "openai" and (m.startswith(("gpt-5", "o1", "o3", "o4")))


def resolve(config: AppConfig, model_name: str | None) -> tuple[Upstream | None, str | None]:
    """(upstream, None) or (None, why not)."""
    name = model_name or (config.models[0].name if config.models else None)
    if not name:
        return None, "no model is configured"
    model_config = config.get_model_config(name)
    if model_config is None:
        return None, f"the model {name!r} is not configured"
    extra = dict(getattr(model_config, "model_extra", None) or {})
    use = str(model_config.use or "")
    if any(use.startswith(prefix) for prefix in _OPENAI_FAMILY):
        base = str(extra.get("base_url") or extra.get("openai_api_base") or "https://api.openai.com/v1").rstrip("/")
        key = str(extra.get("api_key") or extra.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")).strip()
        provider = "openai"
    elif any(use.startswith(prefix) for prefix in _ANTHROPIC):
        base = str(extra.get("base_url") or extra.get("anthropic_api_url") or "https://api.anthropic.com").rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        key = str(extra.get("api_key") or extra.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
        provider = "anthropic"
    else:
        return None, f"the model {name!r} ({use}) cannot be served to the coding worker"
    if not key:
        return None, f"the model {name!r} has no API key in the gateway"
    if not base.startswith("https://") and not base.startswith("http://"):
        return None, f"the model {name!r} has an unusable base_url"
    return Upstream(name=name, model=str(model_config.model), base_url=base, api_key=key, provider=provider), None
