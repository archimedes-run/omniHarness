"""MCP Suite > Build: secrets lifted out of a description, and each build
state in words (app.gateway.mcp_build_flow, pure)."""

from __future__ import annotations

import pytest

from app.gateway.mcp_build_flow import describe_build, extract_secrets, scrub, server_name_from


@pytest.mark.parametrize(
    ("text", "name", "value"),
    [
        ("list my issues with ghp_abcdefghijklmnopqrstuvwxyz0123456789", "GITHUB_TOKEN", "ghp_abcdefghijklmnopqrstuvwxyz0123456789"),
        ("use DEVPOST_TOKEN=dv_9f8e7d6c5b4a and paginate", "DEVPOST_TOKEN", "dv_9f8e7d6c5b4a"),
        ("my password is hunter22secret", "PASSWORD", "hunter22secret"),
        ("fetch weather with a8f5f167f44f4964e6c998dee827110c", "SECRET", "a8f5f167f44f4964e6c998dee827110c"),
        ("post as xoxb-1234567890-abcdefghij", "SLACK_TOKEN", "xoxb-1234567890-abcdefghij"),
    ],
)
def test_a_secret_becomes_a_named_placeholder(text, name, value) -> None:
    out = extract_secrets(text)
    assert value not in out.text
    assert "{{secret:" + name + "}}" in out.text
    assert out.secrets == {name: value}


def test_ordinary_words_are_left_alone() -> None:
    text = "check my Devpost submissions; the token is required for auth"
    out = extract_secrets(text)
    assert out.text == text and out.secrets == {}


def test_the_same_value_twice_is_one_secret_and_placeholders_are_not_reread() -> None:
    v = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    out = extract_secrets(f"{v} and again {v}, secret: zz9988776655aa")
    assert out.secrets["GITHUB_TOKEN"] == v and len(out.secrets) == 2
    assert out.text.count("{{secret:GITHUB_TOKEN}}") == 2


def test_scrub_names_the_secret_it_hides() -> None:
    assert scrub("auth failed for abc123secret", {"API_KEY": "abc123secret"}) == "auth failed for {{secret:API_KEY}}"


def test_a_name_comes_from_the_words_not_the_secret() -> None:
    assert server_name_from("check my Devpost submissions {{secret:TOKEN}}") == "check-devpost-submissions"


def _d(server=None, **kw):
    base = dict(phase=None, error=None, tools=[], test_results=[], deploy_steps=[], testing_now=False, run_status=None, run_error=None, stored_secrets=set())
    base.update(kw)
    return describe_build(server or {"status": "not_running"}, **base)


def test_each_state_in_words() -> None:
    src = {"status": "verified", "source_code": "x", "detected_secrets": []}
    assert _d(run_status="running").state == "drafting"
    assert _d(run_status="error", run_error="model down").reason.endswith("model down")
    assert _d().state == "stalled"  # no code, no run: said, not assumed drafting
    assert _d(src, testing_now=True).state == "building"
    failed = _d({**src, "status": "failed"}, phase="failed", error="reads ~/.ssh")
    assert (failed.state, failed.reason) == ("tests_failed", "reads ~/.ssh")
    no_tools = _d({**src, "status": "testing"}, phase="testing", test_results=[{"tool": "__sandbox__", "ok": False, "error": "SyntaxError"}])
    assert (no_tools.state, no_tools.reason) == ("tests_failed", "SyntaxError")
    waiting = _d(src, phase="verified", tools=[{"name": "a"}], test_results=[{"tool": "a", "ok": True}])
    assert waiting.state == "awaiting_approval" and waiting.label == "Waiting for your approval"
    assert waiting.steps[-1] == {"status": "waiting", "text": "First real run needs your approval"}
    on = _d({**src, "status": "deployed", "approved": True}, phase="deployed")
    assert on.state == "enabled"


def test_a_secret_it_cannot_check_is_said_so() -> None:
    src = {"status": "verified", "source_code": "x", "detected_secrets": ["K"]}
    assert "can't tell" in _d(src, phase="verified", stored_secrets=None).steps[0]["text"]
    assert "not stored yet" in _d(src, phase="verified", stored_secrets=set()).steps[0]["text"]
