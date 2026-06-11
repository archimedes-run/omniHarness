"""Tests for app.gateway.mcp_egress.build_egress_rules.

No DB, no Fernet, no network — pure function.
"""

from __future__ import annotations

from app.gateway.mcp_egress import build_egress_rules


def test_empty_hosts_returns_default_deny_no_allows() -> None:
    rules = build_egress_rules([])
    assert rules["default_policy"] == "deny"
    assert rules["allow"] == []


def test_single_host_gets_port_80_and_443() -> None:
    rules = build_egress_rules(["api.example.com"])
    allows = rules["allow"]
    ports = {r["port"] for r in allows}
    assert ports == {80, 443}
    assert all(r["host"] == "api.example.com" for r in allows)


def test_default_policy_is_always_deny() -> None:
    for hosts in [[], ["a.com"], ["a.com", "b.com"]]:
        assert build_egress_rules(hosts)["default_policy"] == "deny"


def test_duplicate_hosts_are_deduplicated() -> None:
    rules = build_egress_rules(["api.example.com", "api.example.com"])
    hosts_in_rules = [r["host"] for r in rules["allow"]]
    assert hosts_in_rules.count("api.example.com") == 2  # one per port, not four


def test_multiple_distinct_hosts_each_get_two_ports() -> None:
    rules = build_egress_rules(["alpha.com", "beta.com"])
    assert len(rules["allow"]) == 4
    host_set = {r["host"] for r in rules["allow"]}
    assert host_set == {"alpha.com", "beta.com"}


def test_whitespace_in_host_is_stripped() -> None:
    rules = build_egress_rules(["  trimmed.com  "])
    assert all(r["host"] == "trimmed.com" for r in rules["allow"])


def test_empty_string_host_is_ignored() -> None:
    rules = build_egress_rules(["", "  ", "real.com"])
    hosts = {r["host"] for r in rules["allow"]}
    assert "" not in hosts
    assert "real.com" in hosts
