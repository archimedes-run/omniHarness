"""Which secret keys in the environment does nothing use? (startup log, names only)

Dead secrets pile up in ``.env``: a provider tried once, a channel switched off.
Each one is a credential that can leak with nothing to show for it. At startup
the gateway logs one line naming the secret-looking keys that are present but
unused, NAMES ONLY, never a value:

    env: 5 secret key(s) present but unused: FIRECRAWL_API_KEY, ...

A key counts as USED when either

  (a) an ACTIVE ``$VAR`` / ``${VAR}`` reference names it in config.yaml or
      extensions_config.json, inside an entry that is enabled (YAML comments
      are not parsed, and any mapping with ``enabled: false`` is skipped), or
  (b) the code reads it implicitly and the feature that reads it is active:
      :data:`IMPLICIT_ENV_READS`, the ONE registry of such reads. A test keeps
      it from drifting: every secret-named literal ``os.getenv`` /
      ``os.environ`` read under backend/ must be listed here.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: What a secret's NAME looks like (same idea as the host-bash scrub).
SECRET_NAME_RE = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|PRIVATE_KEY|CREDENTIAL|_KEY$)", re.IGNORECASE)

_REF_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")

Predicate = Callable[[dict, dict], bool]


def _always(config: dict, extensions: dict) -> bool:
    return True


def _model_uses(fragment: str) -> Predicate:
    def check(config: dict, extensions: dict) -> bool:
        return any(fragment in str((m or {}).get("use", "")) for m in config.get("models") or [] if isinstance(m, dict))

    return check


def _tool_uses(fragment: str) -> Predicate:
    def check(config: dict, extensions: dict) -> bool:
        return any(fragment in str((t or {}).get("use", "")) for t in config.get("tools") or [] if isinstance(t, dict))

    return check


#: Env keys the code (or a library it calls) reads WITHOUT a config reference,
#: each tied to the feature that must be active for the key to count as used.
#: name -> (feature, predicate over the raw config.yaml and extensions dicts)
IMPLICIT_ENV_READS: dict[str, tuple[str, Predicate]] = {
    "AUTH_JWT_SECRET": ("gateway auth (always)", _always),
    "OMNI_HARNESS_INTERNAL_AUTH_TOKEN": ("internal callers: channels, trigger engine (always)", _always),
    "BETTER_AUTH_SECRET": ("frontend session auth (always)", _always),
    "COMPOSIO_API_KEY": ("Composio connectors: the client is built whenever the key is set (app/gateway/deps.py)", _always),
    "OPENAI_API_KEY": ("any model on langchain_openai (ChatOpenAI reads it implicitly)", _model_uses("langchain_openai")),
    "ANTHROPIC_API_KEY": ("any model on langchain_anthropic", _model_uses("anthropic")),
    "CLAUDE_CODE_OAUTH_TOKEN": ("a model on omniharness.models.claude_provider", _model_uses("claude_provider")),
    "ANTHROPIC_AUTH_TOKEN": ("a model on omniharness.models.claude_provider", _model_uses("claude_provider")),
    "CLAUDE_CODE_CREDENTIALS_PATH": ("a model on omniharness.models.claude_provider", _model_uses("claude_provider")),
    "JINA_API_KEY": ("the jina_ai web_fetch tool", _tool_uses("jina_ai")),
    "SERPER_API_KEY": ("the serper web_search tool", _tool_uses("serper")),
    "TAVILY_API_KEY": ("a tavily tool (the client reads it implicitly)", _tool_uses("tavily")),
    "FIRECRAWL_API_KEY": ("a firecrawl tool (the client reads it implicitly)", _tool_uses("firecrawl")),
    "EXA_API_KEY": ("an exa tool (the client reads it implicitly)", _tool_uses("exa")),
    "INFOQUEST_API_KEY": ("an infoquest tool", _tool_uses("infoquest")),
}


#: Keys the config may name as ``$VAR`` (channels, models, tools, MCP servers).
#: They count as used only when an ENABLED entry references them, but each must
#: be PASSED into the gateway container, or the reference resolves to nothing.
CONFIG_REFERENCE_KEYS: dict[str, str] = {
    "TELEGRAM_BOT_TOKEN": "channels.telegram.bot_token",
    "SLACK_BOT_TOKEN": "channels.slack.bot_token",
    "SLACK_APP_TOKEN": "channels.slack.app_token",
    "DISCORD_BOT_TOKEN": "channels.discord.bot_token",
    "OPENCLAW_BEARER_TOKEN": "channels.openclaw.bearer_token",
    "DEEPSEEK_API_KEY": "a model's api_key",
    "GEMINI_API_KEY": "a model's api_key",
    "GOOGLE_API_KEY": "a model's api_key",
    "OPENROUTER_API_KEY": "a model's api_key",
    "VOLCENGINE_API_KEY": "a model's api_key",
    "MOONSHOT_API_KEY": "a model's api_key",
    "GITHUB_TOKEN": "an MCP server's env (extensions_config.json)",
}

#: Non-secret settings the gateway reads from the environment (.env).
OPERATIONAL_ENV_KEYS: dict[str, str] = {
    "AUTH_TRUSTED_PROXIES": "login rate limiter (routers/auth.py)",
    "ANTHROPIC_BILLING_HEADER": "claude provider",
    "COMPOSIO_USER_ID": "Composio connectors",
    "COMPOSIO_CONNECTED_ACCOUNT_ID": "Composio connectors",
    "COMPOSIO_TOOLKIT": "Composio connectors",
    "COMPOSIO_IMPORTANT_ONLY": "Composio connectors",
    "GATEWAY_ENABLE_DOCS": "gateway docs routes",
    "LANGSMITH_TRACING": "LangSmith tracing (read by langsmith)",
    "LANGSMITH_API_KEY": "LangSmith tracing (read by langsmith)",
    "LANGSMITH_PROJECT": "LangSmith tracing (read by langsmith)",
    "LANGSMITH_ENDPOINT": "LangSmith tracing (read by langsmith)",
    "TZ": "timezone",
}

#: Read by the FRONTEND container, never passed to the gateway.
FRONTEND_ENV_KEYS = frozenset({"BETTER_AUTH_SECRET"})

#: The ONLY environment keys the gateway container is given (docker compose
#: `environment:` entries; there is no env_file). tests/security keeps the
#: compose files equal to this list.
GATEWAY_ENV_KEYS: tuple[str, ...] = tuple(sorted((set(IMPLICIT_ENV_READS) | set(CONFIG_REFERENCE_KEYS) | set(OPERATIONAL_ENV_KEYS)) - FRONTEND_ENV_KEYS))


def env_file_keys_not_passed(env_file: str | Path) -> list[str]:
    """For `make env-check`: keys in the repo .env that NO container receives
    (names only). Compose-interpolation keys used in the compose files count."""
    from dotenv import dotenv_values

    compose_keys = set()
    for compose in ("docker-compose.yaml", "docker-compose-dev.yaml"):
        path = Path(__file__).resolve().parents[3] / "docker" / compose
        if path.is_file():
            compose_keys |= set(_REF_RE.findall(path.read_text(encoding="utf-8")))
    passed = set(GATEWAY_ENV_KEYS) | FRONTEND_ENV_KEYS | compose_keys
    return sorted(k for k in dotenv_values(env_file) if k not in passed)


def _active_refs(node: Any) -> set[str]:
    """$VAR references in enabled entries of a parsed config tree."""
    found: set[str] = set()
    if isinstance(node, dict):
        if node.get("enabled") is False:
            return found
        for value in node.values():
            found |= _active_refs(value)
    elif isinstance(node, list):
        for item in node:
            found |= _active_refs(item)
    elif isinstance(node, str):
        found |= set(_REF_RE.findall(node))
    return found


def unused_secret_keys(present: Iterable[str], config: dict, extensions: dict) -> list[str]:
    """The secret-named keys in ``present`` that nothing active uses."""
    used = _active_refs(config) | _active_refs(extensions)
    for name, (_feature, active) in IMPLICIT_ENV_READS.items():
        try:
            if active(config, extensions):
                used.add(name)
        except Exception:  # noqa: BLE001 - a malformed config must not hide a key
            continue
    return sorted(k for k in set(present) if SECRET_NAME_RE.search(k) and k not in used)


def _env_file_keys() -> set[str]:
    """Keys of the .env this process loaded (load_dotenv walks up from here)."""
    from dotenv import dotenv_values

    seen: set[str] = set()
    for start in (Path.cwd(), Path(__file__).resolve().parent):
        for directory in (start, *start.parents):
            candidate = directory / ".env"
            if candidate.is_file():
                try:
                    seen |= set(dotenv_values(candidate))
                except OSError:
                    pass
                break
    return seen


def _raw(path: Path | None) -> dict:
    if path is None or not Path(path).is_file():
        return {}
    text = Path(path).read_text(encoding="utf-8")
    if str(path).endswith(".json"):
        import json

        return json.loads(text or "{}")
    import yaml

    return yaml.safe_load(text) or {}


def log_unused_secrets() -> list[str]:
    """Startup: one INFO line naming unused secret keys (names only)."""
    from omniharness.config.app_config import AppConfig
    from omniharness.config.extensions_config import ExtensionsConfig

    try:
        config = _raw(AppConfig.resolve_config_path())
    except Exception:  # noqa: BLE001
        config = {}
    try:
        extensions = _raw(ExtensionsConfig.resolve_config_path())
    except Exception:  # noqa: BLE001
        extensions = {}
    # The .env's own keys when it is readable here; otherwise (a container
    # given the file through env_file) the process environment.
    present = _env_file_keys() or {k for k, v in os.environ.items() if v}
    unused = unused_secret_keys(present, config, extensions)
    if unused:
        logger.info("env: %d secret key(s) present but unused: %s", len(unused), ", ".join(unused))
    return unused


if __name__ == "__main__":  # `make env-check`: names only, never values
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else ".env"
    missing = env_file_keys_not_passed(target)
    if missing:
        print(f"env-check: {len(missing)} key(s) in {target} reach no container: {', '.join(missing)}")
    else:
        print(f"env-check: every key in {target} is passed to a container that reads it")
