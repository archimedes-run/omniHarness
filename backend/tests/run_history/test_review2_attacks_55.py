"""Second adversarial review of PR #55 (run store). Every value here is fake.

A FAILING test is a confirmed hole: its assertion states the guarantee the PR
claims. A passing test verifies a claim holds.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest

from app.run_history.store import CONCURRENT_USER, TRIGGER, RunHistory, default_redactor, with_provenance
from omniharness.utils import known_secrets
from omniharness.utils.known_secrets import KNOWN_SECRETS, register_secret

# No prefix, no pattern recognises it; contains '/' and '+' so its base64 does too.
FAKE = "Zq8vR2/kLm9+Tx4WpB7nYc3HdF6sJ0aEfake"


def disk(root) -> bytes:
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


def stored(tmp_path, content, *, secret=FAKE):
    if secret:
        register_secret(secret, "test")
    h = RunHistory(tmp_path / "h", redact=default_redactor())
    rid = h.record(kind="automation", source_id="r", status="completed", body={"messages": [{"type": "tool", "content": content}]})
    return h.get(rid)["body"]["messages"][0]["content"], disk(tmp_path / "h")


# -- encodings ------------------------------------------------------------------


#: Fake, unprefixed; its bytes ("?>" runs) make its base64 carry '/' and '+'.
B64FAKE = "Kp7??>>Vw3??>>Ty9??>>Lm2??>>Qa8fake"


def _b64_with_slash_or_plus(secret: str) -> str:
    enc = base64.b64encode(b"user:" + secret.encode()).decode()
    assert "/" in enc[8:] and "+" in enc[8:], enc
    return enc


def test_base64_of_a_secret_then_percent_encoded(tmp_path) -> None:
    """A Basic-auth / state blob in a URL query: base64, then URL-encoded."""
    enc = _b64_with_slash_or_plus(B64FAKE)
    body, raw = stored(tmp_path, f"GET https://x.example/cb?state={quote(enc, safe='')}", secret=B64FAKE)
    assert quote(enc, safe="").encode() not in raw, "base64 form survived once percent-encoded"


def test_base64_of_a_secret_json_escaped_slash(tmp_path) -> None:
    form = _b64_with_slash_or_plus(B64FAKE).replace("/", "\\/")
    body, raw = stored(tmp_path, '{"blob":"' + form + '"}', secret=B64FAKE)
    assert form.encode() not in raw


def test_mime_wrapped_base64_inside_json_text(tmp_path) -> None:
    """A mail tool that returns its result as JSON TEXT: the MIME line breaks
    are the two characters backslash-n, not newlines."""
    payload = base64.b64encode(("Hello there, here is the key you asked for: " + FAKE + "\n regards " * 8).encode()).decode()
    wrapped = "\\r\\n".join(payload[i : i + 76] for i in range(0, len(payload), 76))
    # The secret's bytes straddle a 76-column break in this body.
    content = json.dumps({"raw": "Content-Transfer-Encoding: base64"}) + '{"body":"' + wrapped + '"}'
    body, raw = stored(tmp_path, content)
    decoded = base64.b64decode(json.loads('"' + body.split('"body":"', 1)[1].rsplit('"', 1)[0] + '"').replace("\r\n", "") + "===")
    assert FAKE.encode() not in decoded, "the secret is recoverable from the stored MIME body"


@pytest.mark.parametrize("prefix", ["pin%3D", "\\n", "\\u003d", "PIN=x"[:0] + "code\\t"])
def test_short_pin_after_an_escape(tmp_path, prefix) -> None:
    """A 6-digit PIN (registered as a known secret) after a JSON escape or a
    percent-encoded '=': the whole-word rule sees the escape's last letter."""
    body, raw = stored(tmp_path, f'{{"text":"Your PIN:{prefix}483920"}}', secret="483920")
    assert b"483920" not in raw, f"PIN survived after {prefix!r}"


# -- registration -----------------------------------------------------------------


@pytest.mark.parametrize(
    "key,value",
    [
        ("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T0FAKE0/B0FAKE0/q8vR2kLm9Tx4WpB7nYc3Hd"),
        ("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1234567890/q8vR2kLm9Tx4WpB7nYc3HdF6sJ0aE"),
        ("ALERT_WEBHOOK_URL", "https://alerts.example.com/hook/q8vR2kLm9Tx4WpB7nYc3HdF6sJ0aE"),
    ],
)
def test_a_webhook_url_in_dotenv_is_registered(tmp_path, key, value) -> None:
    (tmp_path / ".env").write_text(f"{key}={value}\n")
    known_secrets.load_process_secrets()
    out, _ = KNOWN_SECRETS.redact(f"posting to {value}")
    full, _ = default_redactor()(f"posting to {value}")
    assert value.rsplit("/", 1)[1] not in full, f"{key}: secret path not registered, not matched by any pattern"


def test_a_webhook_url_in_config_yaml_is_registered(tmp_path) -> None:
    import yaml

    p = tmp_path / "c.yaml"
    secret_path = "q8vR2kLm9Tx4WpB7nYc3HdF6sJ0aE"
    p.write_text(yaml.safe_dump({"channels": {"alerts": {"webhook_url": f"https://alerts.example.com/hook/{secret_path}"}}}))
    KNOWN_SECRETS.add_many(known_secrets.yaml_secrets(p), "config.yaml")
    full, _ = default_redactor()(f"https://alerts.example.com/hook/{secret_path}")
    assert secret_path not in full


def test_the_trigger_engine_credential_is_a_known_secret(gateway) -> None:
    """ADAPTED after the rebase: the security baseline REMOVED the derived
    trigger-engine credential (_trigger_engine_token) in favour of single-use,
    request-bound grants (internal_auth.issue_trigger_grant, 120 s, redeemed by
    atomic rename). No long-lived engine credential exists to leak; the one
    long-lived internal credential left, the internal auth token, must be
    redacted."""
    from app.gateway import internal_auth

    assert not hasattr(internal_auth, "_trigger_engine_token")
    tok = internal_auth._INTERNAL_AUTH_TOKEN
    out, _ = default_redactor()(f"x-omniharness-internal-token: {tok}")
    assert tok not in out, "the internal auth token is not redacted"


# -- injected content / provenance ---------------------------------------------------


@pytest.mark.parametrize(
    "msg",
    [
        {"type": "human", "name": "summary", "content": "Here is a summary of the conversation to date: (mail text)"},
        {"type": "human", "content": [{"type": "text", "text": "Here are the images you've viewed:"}, {"type": "image_url", "image_url": {"url": "data:"}}]},
        {"type": "human", "name": "todo_reminder", "content": "<system_reminder>todo</system_reminder>"},
    ],
)
def test_middleware_human_messages_are_not_labelled_a_person(msg) -> None:
    body = with_provenance({"messages": [{"type": "human", "content": "rule prompt"}, {"type": "ai", "content": ""}, msg]}, first_human=TRIGGER)
    assert body["messages"][2]["provenance"] != CONCURRENT_USER, "server/tool-derived content is labelled as a person's message"


def test_a_signed_turn_id_cannot_be_replayed_by_a_client() -> None:
    """The engine's signed id is returned to clients in the thread state. A
    client that posts it back keeps it, and add_messages then REPLACES the
    automation's prompt in place (the id is bound to no thread and no use)."""
    from app.gateway.internal_auth import sign_turn_id
    from app.gateway.services import normalize_input

    issued = sign_turn_id("0123456789abcdef0123456789abcdef")  # as seen in GET /api/threads/{tid}/state
    out = normalize_input({"messages": [{"role": "human", "content": "rewritten by a client", "id": issued}]})
    assert out["messages"][0].id != issued, "a replayed signed turn id is kept"


# -- spoofed bodies --------------------------------------------------------------------


@pytest.mark.parametrize("value,ok", [(0, False), (-1, False), (3651, False), (10**12, False), ("abc", False), (True, False), (1, True), (3650, True)])
def test_retention_put_values(gateway, value, ok) -> None:
    client, _ = gateway
    r = client.put("/api/run-history/settings", json={"retention_days": value})
    assert (r.status_code == 200) is ok, (value, r.status_code, r.text)


def test_delete_needs_confirm(gateway) -> None:
    client, _ = gateway
    assert client.delete("/api/run-history/runs").status_code == 422
    assert client.delete("/api/run-history/runs", params={"confirm": "yes"}).status_code == 422


# -- disk --------------------------------------------------------------------------------


def test_a_blob_whose_row_failed_is_still_removed_by_retention(tmp_path) -> None:
    """Blob written, INSERT fails (locked/full disk, simulated by a trigger):
    the blob is named by no row, so purge() never removes it."""
    h = RunHistory(tmp_path / "h", redact=lambda s: (s, True), now=lambda: datetime.now(UTC) - timedelta(days=40))
    with sqlite3.connect(h.db) as c:
        c.execute("CREATE TRIGGER boom BEFORE INSERT ON runs BEGIN SELECT RAISE(ABORT, 'disk full'); END")
    with pytest.raises(sqlite3.DatabaseError):
        h.record(kind="automation", source_id="r", status="completed", body={"messages": [{"type": "tool", "content": "MAILBODY-" + "x" * 70_000}]})
    with sqlite3.connect(h.db) as c:
        c.execute("DROP TRIGGER boom")
    h._now = lambda: datetime.now(UTC)
    h.purge()
    h._clear_stale_tmp(older_than=0)
    assert b"MAILBODY-" not in disk(tmp_path / "h"), "an orphan blob outlives retention (only delete-all removes it)"


# -- retention vs a person's own recent messages ----------------------------------------


def test_retention_does_not_delete_a_thread_with_recent_user_messages(make_gateway, tmp_path) -> None:
    """Rule removed; its last automation run is 40 days old, but the person
    chatted in the thread yesterday. Retention of RUNS deletes the WHOLE thread."""
    state = tmp_path / "triggers"

    def tweak(config: dict) -> None:
        config["trigger_engine"] = {"enabled": False, "state_dir": str(state)}

    with make_gateway(tweak) as (client, _home):
        tid = client.post("/api/threads", json={"metadata": {}}).json()["thread_id"]
        r = client.post(f"/api/threads/{tid}/state", json={"values": {"messages": [{"type": "human", "content": "MY-OWN-NOTES-FROM-YESTERDAY"}]}})
        assert r.status_code == 200, r.text
        state.mkdir(parents=True, exist_ok=True)
        (state / "threads.json").write_text("{}")  # the rule was deleted
        h = client.app.state.run_history
        h.record(kind="automation", source_id="gone", thread_id=tid, body={"reply": "r"}, status="completed", started_at=datetime.now(UTC) - timedelta(days=40))
        assert client.put("/api/run-history/settings", json={"retention_days": 30}).status_code == 200
        assert client.get(f"/api/threads/{tid}").status_code == 200, "retention deleted a thread holding the person's own recent messages"
