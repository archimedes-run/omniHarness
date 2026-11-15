"""The locked frame's view token never reaches nginx's access log (Spec 012 S2).

nginx renders its config from docker/nginx/nginx.conf at container start (the
compose command copies it), so this checks the file the container reads: the
`preview_safe` log format logs `$safe_request_uri`, whose map redacts the
frame route's query. The map's regex is replayed here with Python's engine
(PCRE and Python agree on this pattern)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("conf", ["docker/nginx/nginx.conf", "docker/nginx/nginx.local.conf"])
def test_the_frame_query_is_redacted_in_the_access_log(conf):
    text = (ROOT / conf).read_text()
    assert re.search(r"log_format preview_safe [^;]*\$safe_request_uri", text, re.S)
    block = re.search(r"map \$request_uri \$safe_request_uri \{(.*?)\n    \}", text, re.S).group(1)
    line = next(ln.strip() for ln in block.splitlines() if "frame" in ln and ln.strip().startswith("~"))
    pattern, repl = line[1:].rstrip(";").split(" ", 1)
    pattern = pattern.replace("(?<", "(?P<")
    uri = "/api/artifacts/abc/versions/1/frame.html?t=SECRET.TOKEN&path=x"
    m = re.match(pattern, uri)
    assert m is not None
    logged = repl.replace("$frame_path", m.group("frame_path"))
    assert logged == "/api/artifacts/abc/versions/1/frame.html?[redacted]" and "SECRET" not in logged
    assert re.match(pattern, "/api/artifacts/abc/versions/1/frame.html") is None  # no query: logged as is


def test_the_gateway_log_filter_redacts_the_frame_query():
    from app.gateway.logging_filters import mask_preview_token_urls

    out = mask_preview_token_urls('"GET /api/artifacts/a/versions/1/frame.html?t=SECRET.x&path=b HTTP/1.1" 200')
    assert "SECRET" not in out and "/frame.html?[redacted] HTTP/1.1" in out
