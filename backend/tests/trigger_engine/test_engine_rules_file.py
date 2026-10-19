"""The trigger engine's rule file at startup (Article XIV).

Moved from tests/trigger_engine/test_wiring.py when that file's wiring scan
(Gate 4, app/trigger_engine only) was replaced by tests/gates/test_wiring.py,
which covers every module (Feature 004 T079). These two tests were never part
of the scan.
"""

from __future__ import annotations


def test_a_missing_rule_file_stops_the_engine_rather_than_running_empty(tmp_path):
    """The audit finding this closes.

    Previously: a missing rule file logged an error, produced an empty config,
    and the engine started and reported `running: True`. Every
    proactive-message requirement was inert while the operator surface said
    healthy — which is worse than a crash, because a crash gets investigated.
    """
    from types import SimpleNamespace

    import pytest

    from app.gateway.trigger_engine_wiring import build_loop

    cfg = SimpleNamespace(
        trigger_engine=SimpleNamespace(
            rules_path=str(tmp_path / "absent.json"),
            state_dir=str(tmp_path / "state"),
            actor="default",
            tick_seconds=30.0,
        ),
        database=SimpleNamespace(backend="memory", postgres_url=""),
    )

    with pytest.raises(RuntimeError, match="no rules are in effect"):
        build_loop(cfg, gateway_post=lambda *a: {}, gateway_put=lambda *a: {}, gateway_get=lambda *a: {}, fetch_sessions=lambda: {}, exchange_state=lambda tid: {}, remote=None)


def test_the_shipped_defaults_load_and_are_all_disabled():
    """A shipped default must exist and parse — and must NOT start messaging
    someone because they installed the software."""

    from app.gateway.trigger_engine_wiring import DEFAULT_RULES
    from app.trigger_engine.config import ConfigLoader

    assert DEFAULT_RULES.exists(), "the engine ships no default rule file"

    cfg = ConfigLoader(path=DEFAULT_RULES).load()

    assert cfg.rules, "the shipped defaults parse to zero rules"
    assert all(not rule.enabled for rule in cfg.rules), "a shipped rule is ENABLED; installing must not start proactive messaging"
