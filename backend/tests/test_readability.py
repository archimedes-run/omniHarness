"""Tests for readability extraction fallback behavior."""

import subprocess

import pytest

from omniharness.utils.readability import ReadabilityExtractor


@pytest.fixture
def readability_js(monkeypatch):
    """These tests are about the node path: pretend its dependencies are installed."""
    monkeypatch.setattr("omniharness.utils.readability.readability_js_installed", lambda: True)


def test_extract_article_falls_back_when_readability_js_fails(monkeypatch, readability_js):
    """When Node-based readability fails, extraction should fall back to Python mode."""

    calls: list[bool] = []

    def _fake_simple_json_from_html_string(html: str, use_readability: bool = False):
        calls.append(use_readability)
        if use_readability:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["node", "ExtractArticle.js"],
                stderr="boom",
            )
        return {"title": "Fallback Title", "content": "<p>Fallback Content</p>"}

    monkeypatch.setattr(
        "omniharness.utils.readability.simple_json_from_html_string",
        _fake_simple_json_from_html_string,
    )

    article = ReadabilityExtractor().extract_article("<html><body>test</body></html>")

    assert calls == [True, False]
    assert article.title == "Fallback Title"
    assert article.html_content == "<p>Fallback Content</p>"


def test_extract_article_re_raises_unexpected_exception(monkeypatch, readability_js):
    """Unexpected errors should be surfaced instead of silently falling back."""

    calls: list[bool] = []

    def _fake_simple_json_from_html_string(html: str, use_readability: bool = False):
        calls.append(use_readability)
        if use_readability:
            raise RuntimeError("unexpected parser failure")
        return {"title": "Should Not Reach Fallback", "content": "<p>Fallback</p>"}

    monkeypatch.setattr(
        "omniharness.utils.readability.simple_json_from_html_string",
        _fake_simple_json_from_html_string,
    )

    with pytest.raises(RuntimeError, match="unexpected parser failure"):
        ReadabilityExtractor().extract_article("<html><body>test</body></html>")
    assert calls == [True]


def test_without_installed_js_dependencies_nothing_is_spawned_and_npm_never_runs(monkeypatch):
    """readabilipy's node check runs `npm install` (to the internet) when its
    node_modules is missing, as in the gateway image: the pure-Python path is
    used instead, and no process is started at all."""
    import readabilipy.simple_json
    import readabilipy.utils

    spawned: list = []

    def spy(*args, **kwargs):
        spawned.append(args[0] if args else kwargs.get("args"))
        raise AssertionError(f"spawned {spawned[-1]!r}")

    monkeypatch.setattr("omniharness.utils.readability.readability_js_installed", lambda: False)
    monkeypatch.setattr(subprocess, "run", spy)
    monkeypatch.setattr(subprocess, "Popen", spy)
    monkeypatch.setattr(readabilipy.utils, "run_npm_install", lambda: spawned.append("npm install"))
    monkeypatch.setattr(readabilipy.simple_json, "run_npm_install", lambda: spawned.append("npm install"))
    article = ReadabilityExtractor().extract_article("<html><head><title>T</title></head><body><p>Pure Python path text.</p></body></html>")
    assert spawned == []
    assert "Pure Python path text." in article.html_content


def test_the_js_dependency_check_looks_at_readabilipys_node_modules(monkeypatch):
    import os

    import readabilipy.simple_json

    from omniharness.utils.readability import readability_js_installed

    seen: list[str] = []
    monkeypatch.setattr(os.path, "isdir", lambda path: seen.append(path) or False)
    assert readability_js_installed() is False
    assert seen == [os.path.join(os.path.dirname(readabilipy.simple_json.__file__), "javascript", "node_modules")]
