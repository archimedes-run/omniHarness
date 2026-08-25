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


# ---------------------------------------------------------------------------
# Feature 003 (FR-022) — email bodies and page content
#
# These input shapes are WIDER and LESS STRUCTURED than anything the earlier
# features handled: session records are machine-written, agent output is prose
# the assistant composed, and both are narrow next to arbitrary human
# correspondence and arbitrary HTML.
#
# Widened in the redactor's OWN suite so a pattern change made for Feature 003
# cannot silently break Features 001 or 002 — the earlier tests in this file are
# what would catch that, and they run alongside these.
# ---------------------------------------------------------------------------


class TestFeature003InputShapes:
    """Shapes that appear in mail and web pages and not in session records."""

    def test_a_password_reset_link_is_redacted(self):
        body = "Click here to reset: https://accounts.example.com/reset?token=aZ39kd0Lm2Xq8s1PpQ7w"

        out = redact(body, channel=Channel.REMOTE)

        assert "aZ39kd0Lm2Xq8s1PpQ7w" not in out
        assert "[redacted" in out

    def test_a_magic_login_link_is_redacted(self):
        body = "Sign in: https://app.example.com/magic?k=abcd1234efgh5678ijkl"

        assert "abcd1234efgh5678ijkl" not in redact(body, channel=Channel.REMOTE)

    def test_an_access_token_in_a_url_is_redacted(self):
        page = "redirected to https://example.com/cb#access_token=ya29.A0ARrdaM9xKq2Lp&state=xyz"

        assert "ya29.A0ARrdaM9xKq2Lp" not in redact(page, channel=Channel.REMOTE)

    def test_a_one_time_code_quoted_from_mail_is_redacted(self):
        body = "Your verification code is 493028. It expires in 10 minutes."

        assert "493028" not in redact(body, channel=Channel.REMOTE)

    def test_a_bare_six_digit_number_is_not_redacted(self):
        """The discriminator. Redacting every 6-digit number would eat years,
        prices and room numbers, and a redactor that mangles ordinary prose gets
        turned off."""
        body = "The 2026 offsite is in room 401829 and the budget is 250000."

        out = redact(body, channel=Channel.REMOTE)

        assert "401829" in out
        assert "250000" in out

    def test_a_card_number_in_a_receipt_is_redacted(self):
        body = "Charged to 4111 1111 1111 1111 on 24 August."

        assert "4111 1111 1111 1111" not in redact(body, channel=Channel.REMOTE)

    def test_a_stripe_live_key_is_redacted(self):
        assert "sk_live_51ABCdefGHIjklMNO" not in redact("key sk_live_51ABCdefGHIjklMNO here", channel=Channel.REMOTE)

    def test_a_cookie_header_from_a_page_fetch_is_redacted(self):
        page = "Set-Cookie: session=eyJhbGciOiJIUzI1NiJ9abcdef; Path=/"

        assert "eyJhbGciOiJIUzI1NiJ9abcdef" not in redact(page, channel=Channel.REMOTE)

    def test_ordinary_email_prose_survives_intact(self):
        """The most important test here.

        A redactor that mangles normal mail is one the user disables, and a
        disabled redactor protects nothing. Over-redaction is not the safe
        direction when it destroys the feature.
        """
        body = "Hi Darcy,\n\nThanks for the notes. Tuesday at 3pm works — I've held it. The Q3 numbers are in the deck on page 4, and the 2026 forecast is on 7.\n\nBest,\nRishabh"

        assert redact(body, channel=Channel.REMOTE) == body

    def test_a_calendar_description_survives_intact(self):
        description = "Weekly sync. Agenda: Q3 plan, hiring, the 2026 roadmap. Room 401."

        assert redact(description, channel=Channel.REMOTE) == description

    def test_widening_did_not_weaken_the_earlier_patterns(self):
        """FR-022's actual requirement: a change for 003 must not break 001/002.

        The rest of this file is the real guard — it runs unchanged. This is a
        spot check that the shapes those features care about still redact.
        """
        for secret, sample in [
            ("sk-abcdefghijklmnop1234", "OPENAI_API_KEY=sk-abcdefghijklmnop1234"),
            ("AKIAIOSFODNN7EXAMPLE", "aws id AKIAIOSFODNN7EXAMPLE"),
            ("ghp_abcdefghijklmnopqrstuvwxyz012345", "token ghp_abcdefghijklmnopqrstuvwxyz012345"),
        ]:
            assert secret not in redact(sample, channel=Channel.REMOTE), f"{secret} is no longer redacted"

    def test_the_limit_is_still_stated_honestly(self):
        """Article X. These are RECOGNIZED shapes; an unrecognized one passes
        through, and the wording must not imply otherwise."""
        invented = "my passphrase is correct-horse-battery-staple"

        assert redact(invented, channel=Channel.REMOTE) == invented


class TestUnexpectedInputFailsClosed:
    """The removed None guard, pinned as behaviour.

    `redact` once began `if text is None: return ""`. mypy reported it
    unreachable — the parameter is `str` — and tracing every caller confirmed
    nothing passes None, in production or tests.

    Dead was not the worst of it. Returning "" reads downstream as
    "successfully redacted to nothing" and DELIVERS. Falling through to the
    broad handler raises RedactionError, and `redact_or_suppress` SUPPRESSES.
    On a security path those are opposite outcomes, and the guard short-circuited
    the safe one.
    """

    def test_none_raises_rather_than_returning_empty(self):
        with pytest.raises(RedactionError):
            redact(None, channel=Channel.REMOTE)

    def test_none_suppresses_delivery(self):
        safe, ok = redact_or_suppress(None, channel=Channel.REMOTE)

        assert ok is False, "unexpected input must suppress delivery, not deliver an empty message"
        assert safe != ""

    @pytest.mark.parametrize("value", [None, 42, [], {}, object()])
    def test_any_non_text_suppresses(self, value):
        """Not just None. Whatever arrives that is not text fails closed."""
        _, ok = redact_or_suppress(value, channel=Channel.REMOTE)

        assert ok is False

    def test_the_empty_string_is_still_a_valid_input(self):
        """The discriminator. "" is legitimately empty text and must pass
        through — otherwise this change would suppress every empty summary."""
        safe, ok = redact_or_suppress("", channel=Channel.REMOTE)

        assert ok is True
        assert safe == ""
