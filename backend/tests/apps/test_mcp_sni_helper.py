"""The SNI-equals-CONNECT helper Squid asks (#59), run as Squid runs it."""

from __future__ import annotations

import subprocess

from app.gateway.mcp_runtime import EGRESS_DIR

CASES = [
    ("api.github.com api.github.com", "OK"),
    ("API.GitHub.com. api.github.com", "OK"),  # same normalisation as the CONNECT host
    ("- api.github.com", "ERR"),  # no SNI sent
    ("github.com api.github.com", "ERR"),  # another (allowlisted) host
    ("evil.example api.github.com", "ERR"),
    ("api.github.com.evil api.github.com", "ERR"),
]


def test_sni_must_equal_the_connect_host() -> None:
    stdin = "".join(line + "\n" for line, _ in CASES)
    out = subprocess.run(["/bin/sh", str(EGRESS_DIR / "sni_check.sh")], input=stdin, capture_output=True, text=True, timeout=10).stdout.split()
    assert out == [want for _, want in CASES]


def test_the_rendered_config_requires_both_rules_on_one_splice() -> None:
    from app.gateway.mcp_egress_config import render_squid

    conf = render_squid(hosts=["a.com"], internal_ip="10.0.0.2", upstream_ip="10.0.0.3", token="ab" * 24)
    assert "ssl_bump splice sni_ok sni_matches_connect" in conf
    assert "%ssl::>sni %DST /opt/omni/sni_check.sh" in conf
