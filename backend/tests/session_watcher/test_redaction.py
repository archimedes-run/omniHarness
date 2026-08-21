"""T033/T034 — redaction on every channel, failing closed, visibly (FR-011c-f)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from session_watcher import redaction
from session_watcher.redaction import MARKER, Channel, RedactionError, redact, redact_or_suppress

SECRETS = [
    "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY",
    "used Bearer sk-ant-api03-abcdefghijklmnopqrstuv",
    "postgresql://admin:hunter2@db.internal:5432/prod",
    "AKIAIOSFODNN7EXAMPLE",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "xoxb-1234567890-abcdefghijkl",
]


@pytest.mark.parametrize("secret", SECRETS)
@pytest.mark.parametrize("channel", [Channel.LOCAL, Channel.REMOTE])
def test_recognized_patterns_are_removed_on_every_channel(secret, channel) -> None:
    """FR-011c: local too. Aggressiveness varies; whether it runs does not."""
    out = redact(f"note: {secret} end", channel)
    payload = secret.split("=")[-1].split("@")[0].split()[-1]
    assert payload not in out, f"{channel}: leaked {payload!r}"
    assert MARKER in out


def test_redactions_are_visible_never_silent() -> None:
    """FR-011f: a silent drop yields a message that reads complete but is not."""
    out = redact("token: ghp_abcdefghijklmnopqrstuvwxyz0123456789", Channel.REMOTE)
    assert MARKER in out
    assert "token:" in out  # surrounding prose survives


def test_uri_credentials_keep_scheme_and_host_shape() -> None:
    out = redact("postgresql://admin:hunter2@db.internal:5432/prod", Channel.LOCAL)
    assert "hunter2" not in out and "admin" not in out
    assert out.startswith("postgresql://") and "db.internal" in out


def test_local_keeps_paths_and_code_remote_reduces_them() -> None:
    """SC-004m — the aggressiveness difference, in both directions."""
    text = "See /Users/dev/projects/app/main.py\n\n```python\nx = 1\n```\n"
    local = redact(text, Channel.LOCAL)
    remote = redact(text, Channel.REMOTE)
    assert "/Users/dev/projects/app/main.py" in local
    assert "x = 1" in local
    assert "/Users/dev/projects" not in remote
    assert "main.py" in remote  # the useful leaf survives
    assert "x = 1" not in remote
    assert "[code]" in remote


def test_failure_suppresses_the_send_rather_than_passing_through(monkeypatch) -> None:
    """FR-011e: fail closed. No path sends unredacted content on error."""

    def boom(text):
        raise ValueError("pattern engine exploded")

    monkeypatch.setattr(redaction, "_apply_patterns", boom)
    with pytest.raises(RedactionError):
        redact("AKIAIOSFODNN7EXAMPLE", Channel.REMOTE)

    text, ok = redact_or_suppress("AKIAIOSFODNN7EXAMPLE", Channel.REMOTE)
    assert ok is False
    assert "AKIAIOSFODNN7EXAMPLE" not in text
    assert "check locally" in text


def test_clean_text_passes_through_unharmed() -> None:
    msg = "All 41 tests passed. The migration took four minutes."
    assert redact(msg, Channel.REMOTE) == msg


def test_sensitive_fixture_is_fully_scrubbed() -> None:
    raw = (Path(__file__).parent / "fixtures" / "sensitive_session.jsonl").read_text()
    out = redact(raw, Channel.REMOTE)
    for leak in ("wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY", "hunter2", "sk-ant-api03-abcdefghijklmnop"):
        assert leak not in out


# --- T034: the weaker claim (FR-011d, Article X) ---------------------------


def test_no_surface_claims_to_remove_secrets() -> None:
    """We remove RECOGNIZED PATTERNS. Claiming more is a defect, not a typo.

    Scans the module's own text: docstrings, messages, identifiers. Pattern
    matching cannot honour "removes secrets", so nothing may say it does.
    """
    src = Path(redaction.__file__).read_text()
    forbidden = re.compile(
        r"(removes?|strips?|scrubs?|eliminates?)\s+(all\s+)?secrets\b|no\s+secrets\s+(will|can)",
        re.IGNORECASE,
    )
    hits = forbidden.findall(src)
    assert not hits, f"overclaiming language in redaction.py: {hits}"
    assert "recognized" in src.lower() or "recognised" in src.lower()


def test_unrecognized_shapes_pass_through_and_that_is_documented() -> None:
    """The stated limitation, asserted so it stays true.

    A secret in a shape we do not recognise survives. That is the honest limit of
    pattern matching, and the docs say so rather than implying completeness.
    """
    novel = "the passphrase is correct-horse-battery-staple"
    assert novel in redact(novel, Channel.REMOTE)
    src = Path(redaction.__file__).read_text().lower()
    assert "not an assertion that secrets take only these shapes" in src


# --- Both input shapes (feature 002, T033) ----------------------------------
#
# The redactor is shared: Feature 001 feeds it session-record text, Feature 002
# feeds it arbitrary agent-composed output. Its own suite must own BOTH shapes,
# so a pattern change made for one consumer cannot silently break the other.
# That cross-consumer regression is the entire risk of sharing the module, and
# nothing else in either feature's tests would catch it.

AGENT_OUTPUT_SECRETS = [
    ("gcp-service-account", '{"type": "service_account", "project_id": "x"}'),
    ("gcp-api-key", "AIzaSyD-1234567890abcdefghijklmnopqrstu"),
    ("jwt", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
    ("openai-project-key", "sk-proj-abcdefghijklmnopqrstuvwx"),
    ("private-key-header", "-----BEGIN RSA PRIVATE KEY-----"),
    ("basic-auth", "Authorization: Basic dXNlcjpzdXBlcnNlY3JldA=="),
]


@pytest.mark.parametrize("name,secret", AGENT_OUTPUT_SECRETS, ids=[n for n, _ in AGENT_OUTPUT_SECRETS])
@pytest.mark.parametrize("channel", [Channel.LOCAL, Channel.REMOTE])
def test_agent_output_shapes_are_redacted(name, secret, channel) -> None:
    """Feature 002's input shape (FR-008c)."""
    out = redact(f"The agent said: {secret} — end", channel)
    assert MARKER in out, f"{name} not recognized on {channel}"


@pytest.mark.parametrize("secret", SECRETS)
def test_session_record_shapes_still_redacted_after_widening(secret) -> None:
    """Feature 001's input shape, re-asserted AFTER the widening.

    This is the regression the shared module risks: a pattern added for 002
    that shadows or breaks one of 001's. Asserted here rather than in either
    consumer, because neither consumer's suite guards the other's shapes.
    """
    out = redact(f"note: {secret} end", Channel.REMOTE)
    payload = secret.split("=")[-1].split("@")[0].split()[-1]
    assert payload not in out


def test_widening_did_not_strengthen_the_claim() -> None:
    """FR-008d — more coverage does NOT license a stronger promise.

    Re-runs the overclaiming scan after the pattern set grew, because that is
    exactly when someone is tempted to upgrade the wording.
    """
    src = Path(redaction.__file__).read_text()
    forbidden = re.compile(
        r"(removes?|strips?|scrubs?|eliminates?)\s+(all\s+)?secrets\b|no\s+secrets\s+(will|can)",
        re.IGNORECASE,
    )
    assert not forbidden.findall(src)
    assert "not an assertion that secrets take only these shapes" in src.lower()


def test_prose_survives_the_widened_patterns() -> None:
    """A widened set must not start eating ordinary text."""
    msg = "All 41 tests passed. The migration took four minutes and finished cleanly."
    assert redact(msg, Channel.REMOTE) == msg
