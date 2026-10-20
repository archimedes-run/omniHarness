"""The startup line naming unused secret keys: names only, never values."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[2]

#: The live .env's key NAMES (from the lead's audit), with fake values.
LIVE_SHAPED_ENV = {
    "OMNI_HARNESS_ROOT": "/fake/root",
    "COMPOSIO_API_KEY": "fake-composio-value-1",
    "JINA_API_KEY": "fake-jina-value-2",
    "OPENAI_API_KEY": "fake-openai-value-3",
    "AUTH_JWT_SECRET": "fake-jwt-value-4",
    "TELEGRAM_BOT_TOKEN": "fake-telegram-value-5",
    "OPENCLAW_BEARER_TOKEN": "fake-openclaw-value-6",
    "INFOQUEST_API_KEY": "fake-infoquest-value-7",
    "TAVILY_API_KEY": "fake-tavily-value-8",
    "FIRECRAWL_API_KEY": "fake-firecrawl-value-9",
    "SERPER_API_KEY": "fake-serper-value-10",
}

LIVE_SHAPED_CONFIG = """
models:
  - name: default
    use: langchain_openai:ChatOpenAI
    model: gpt-test
tools:
  - name: web_search
    use: omniharness.community.ddg_search.tools:web_search_tool
  # - name: web_search
  #   use: omniharness.community.serper.tools:web_search_tool
  #   api_key: $SERPER_API_KEY
  # - name: web_search
  #   use: omniharness.community.tavily.tools:web_search_tool
  #   api_key: $TAVILY_API_KEY
  - name: web_fetch
    use: omniharness.community.jina_ai.tools:web_fetch_tool
channels:
  telegram:
    enabled: true
    bot_token: $TELEGRAM_BOT_TOKEN
  slack:
    enabled: false
    bot_token: $SLACK_BOT_TOKEN
"""


def test_the_live_shaped_env_reports_exactly_the_five_dead_keys(tmp_path, monkeypatch, caplog) -> None:
    from app.gateway.secret_usage import log_unused_secrets

    (tmp_path / ".env").write_text("".join(f"{k}={v}\n" for k, v in LIVE_SHAPED_ENV.items()))
    (tmp_path / "config.yaml").write_text(LIVE_SHAPED_CONFIG)
    (tmp_path / "extensions.json").write_text('{"mcpServers": {"gh": {"enabled": false, "env": {"GITHUB_TOKEN": "$GITHUB_PERSONAL_ACCESS_TOKEN"}}}}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(tmp_path / "extensions.json"))
    with caplog.at_level(logging.INFO, logger="app.gateway.secret_usage"):
        unused = log_unused_secrets()
    assert unused == ["FIRECRAWL_API_KEY", "INFOQUEST_API_KEY", "OPENCLAW_BEARER_TOKEN", "SERPER_API_KEY", "TAVILY_API_KEY"]
    assert "env: 5 secret key(s) present but unused: FIRECRAWL_API_KEY, INFOQUEST_API_KEY, OPENCLAW_BEARER_TOKEN, SERPER_API_KEY, TAVILY_API_KEY" in caplog.text
    for value in LIVE_SHAPED_ENV.values():
        assert value not in caplog.text


def test_a_reference_in_a_disabled_or_commented_entry_does_not_count() -> None:
    from app.gateway.secret_usage import unused_secret_keys

    config = yaml.safe_load(LIVE_SHAPED_CONFIG)
    assert "SLACK_BOT_TOKEN" in unused_secret_keys(["SLACK_BOT_TOKEN"], config, {})
    config["channels"]["slack"]["enabled"] = True
    assert unused_secret_keys(["SLACK_BOT_TOKEN"], config, {}) == []


def test_every_secret_named_env_read_in_the_code_is_in_the_registry() -> None:
    """The registry cannot drift: a new literal os.getenv/os.environ read of a
    secret-named key must be added to IMPLICIT_ENV_READS (with its feature)."""
    from app.gateway.secret_usage import IMPLICIT_ENV_READS, SECRET_NAME_RE

    read = re.compile(r"""os\.(?:getenv|environ\.get|environ\.setdefault)\(\s*["']([A-Z0-9_]+)["']|os\.environ\[\s*["']([A-Z0-9_]+)["']\s*\]""")
    missing = {}
    for root in ("app", "packages"):
        for path in (BACKEND / root).rglob("*.py"):
            if "tests" in path.parts:
                continue
            for a, b in read.findall(path.read_text(errors="ignore")):
                name = a or b
                if SECRET_NAME_RE.search(name) and name not in IMPLICIT_ENV_READS:
                    missing.setdefault(name, str(path.relative_to(BACKEND)))
    assert not missing, f"secret-named env reads not in secret_usage.IMPLICIT_ENV_READS: {missing}"
