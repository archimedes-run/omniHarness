"""Exact-match redaction (omniharness.utils.known_secrets) in the run history.

Every value below is FAKE and shaped so that NO credential pattern recognises
it: a bare token with no prefix. `test_the_patterns_alone_miss_these_values`
proves that, so when a stored run comes back clean, it is the exact-match pass
that cleaned it. Disable that pass (store.default_redactor) and the tests
through the app fail.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

import pytest

from omniharness.utils.known_secrets import KNOWN_SECRETS, KnownSecrets

# Fake, prefix-less, with + and / so the URL-encoded form differs from the raw.
ENV_VALUE = "Zq8v+N3kLp0/Wm7Rt2Yx5Bc9Hd4Jf6Gs1A"
CONFIG_VALUE = "Qm4Xr8Tz2Lp6Vn0Kw3Hs7Jd1Fb5Gy9CeU"
VAULT_VALUE = "Vt5Hn2Ws8Kd4Pq1Lz7Mx3Rb9Jc6Fy0GaE"
REFRESHED_VALUE = "Rf3Gk9Nw1Ty5Hm7Lq2Vx8Sb4Pd6Jz0CuA"
CLI_VALUE_1 = "Cl1Aa2Bb3Cc4Dd5Ee6Ff7Gg8Hh9Ii0JjK"
CLI_VALUE_2 = "Cl2Kk3Ll4Mm5Nn6Oo7Pp8Qq9Rr0Ss1TtU"


def forms_of(value: str) -> dict[str, str]:
    raw = value.encode()
    return {
        "raw": value,
        "base64": base64.b64encode(raw).decode(),
        "base64url-unpadded": base64.urlsafe_b64encode(raw).decode().rstrip("="),
        "url-encoded": quote(value, safe=""),
        "form-encoded": quote_plus(value, safe=""),
    }


def tool_output(*values: str) -> str:
    parts = []
    for v in values:
        for name, form in forms_of(v).items():
            parts.append(f"{name}: {form}")
    return "Fetched the page. " + " | ".join(parts) + " | end."


def on_disk(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


def assert_absent(blob: str | bytes, *values: str) -> None:
    data = blob.decode("latin-1") if isinstance(blob, bytes) else blob
    for v in values:
        for name, form in forms_of(v).items():
            assert form not in data, f"the {name} form of a known secret was stored ({v[:4]}…)"


def record_and_read(client, *values: str) -> tuple[dict, bytes]:
    history = client.app.state.run_history
    run_id = history.record(
        kind="automation",
        source_id="research",
        status="completed",
        body={"messages": [{"type": "tool", "name": "web_fetch", "content": tool_output(*values)}], "reply": "done"},
    )
    resp = client.get(f"/api/run-history/runs/{run_id}")
    assert resp.status_code == 200
    return resp.json(), on_disk(history.root)


# -- the premise ------------------------------------------------------------------


@pytest.mark.parametrize("value", [ENV_VALUE, CONFIG_VALUE, VAULT_VALUE, REFRESHED_VALUE, CLI_VALUE_1, CLI_VALUE_2])
def test_the_patterns_alone_miss_these_values(value) -> None:
    """Without this, a clean result could be the regexes' doing."""
    from app.run_history.store import default_redactor

    patterns_only = default_redactor(known=KnownSecrets())
    out, ok = patterns_only(tool_output(value))
    assert ok and forms_of(value)["raw"] in out and forms_of(value)["base64"] in out


def test_every_encoded_form_is_replaced() -> None:
    known = KnownSecrets()
    known.add(ENV_VALUE, "test")
    out, n = known.redact(tool_output(ENV_VALUE))
    assert_absent(out, ENV_VALUE)
    assert n >= len(forms_of(ENV_VALUE)) and "[redacted]" in out


def test_short_and_plain_configuration_values_are_not_registered() -> None:
    from omniharness.utils.known_secrets import secret_values_in

    found = secret_values_in({"port": "8001", "debug": "true", "base_url": "http://localhost:2024", "path": "/var/data/x", "api_key": "abcdefgh1", "db": "postgres://u:hunter2pass@db/x"})
    assert "abcdefgh1" in found and "hunter2pass" in found
    assert not {"8001", "true", "http://localhost:2024", "/var/data/x"} & set(found)


# -- through create_app() and its lifespan ------------------------------------------


def test_env_and_config_values_are_redacted_by_value(make_gateway, tmp_path) -> None:
    (tmp_path / ".env").write_text(f"ACME_SERVICE_TOKEN={ENV_VALUE}\nPORT=8001\n")

    def tweak(config: dict) -> None:
        config["models"][0]["api_key"] = CONFIG_VALUE

    with make_gateway(tweak) as (client, _):
        detail, disk = record_and_read(client, ENV_VALUE, CONFIG_VALUE)

    assert_absent(json.dumps(detail), ENV_VALUE, CONFIG_VALUE)
    assert_absent(disk, ENV_VALUE, CONFIG_VALUE)
    assert "web_fetch" in json.dumps(detail) and detail["body"]["reply"] == "done", "the run itself was lost"


def test_vault_values_are_known_from_startup(make_gateway, tmp_path) -> None:
    """A secret stored in the MCP vault by an earlier gateway is decrypted and
    registered when the next gateway starts, before any run is recorded."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()

    def tweak(config: dict) -> None:
        config["mcp_builder"] = {"enabled": True, "dev_mode": True, "vault_key": key}

    with make_gateway(tweak) as (client, _):
        vault = client.app.state.mcp_secrets_vault
        assert vault is not None
        client.portal.call(lambda: vault.store(server_id="srv-1", owner_id="owner", key_name="ACME_KEY", plaintext_value=VAULT_VALUE))

    KNOWN_SECRETS.clear()  # a fresh process: only startup loading can know it

    with make_gateway(tweak) as (client, _):
        detail, disk = record_and_read(client, VAULT_VALUE)

    assert_absent(json.dumps(detail), VAULT_VALUE)
    assert_absent(disk, VAULT_VALUE)


class _Resp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _Client:
    def __init__(self, *a, **k) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data):
        return _Resp({"access_token": REFRESHED_VALUE, "token_type": "Bearer", "expires_in": 3600})


def test_a_refreshed_oauth_token_joins_the_set(make_gateway, monkeypatch) -> None:
    from omniharness.config.extensions_config import ExtensionsConfig
    from omniharness.mcp.oauth import OAuthTokenManager

    monkeypatch.setattr("httpx.AsyncClient", _Client)
    oauth = {"enabled": True, "token_url": "https://auth.example.com/token", "grant_type": "client_credentials", "client_id": "cid", "client_secret": "fake-client-secret-value"}
    config = ExtensionsConfig.model_validate({"mcpServers": {"crm": {"enabled": True, "type": "http", "url": "https://crm.example.com/mcp", "oauth": oauth}}})

    with make_gateway() as (client, _):
        asyncio.run(OAuthTokenManager.from_extensions_config(config).get_authorization_header("crm"))
        detail, disk = record_and_read(client, REFRESHED_VALUE)

    assert_absent(json.dumps(detail), REFRESHED_VALUE)
    assert_absent(disk, REFRESHED_VALUE)


def test_an_oauth_credential_file_refreshed_on_disk_is_reloaded(make_gateway, tmp_path) -> None:
    """The Claude Code CLI refreshes its token file under us; the new value is
    picked up when the file changes, without a restart."""
    creds = tmp_path / "fake-home" / ".claude" / ".credentials.json"
    creds.parent.mkdir(parents=True)
    creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": CLI_VALUE_1, "refreshToken": "fake-refresh-0001"}}))

    with make_gateway() as (client, _):
        detail, _disk = record_and_read(client, CLI_VALUE_1)
        assert_absent(json.dumps(detail), CLI_VALUE_1)

        creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": CLI_VALUE_2, "refreshToken": "fake-refresh-0002"}}))
        KNOWN_SECRETS._last_check = float("-inf")
        detail, disk = record_and_read(client, CLI_VALUE_2)

    assert_absent(json.dumps(detail), CLI_VALUE_2)
    assert_absent(disk, CLI_VALUE_1, CLI_VALUE_2)
