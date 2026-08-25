"""Registering the policy layer with the harness (FR-002).

The harness owns the seam (`agents/middlewares/policy_hook.py`); the application
fills it. This is the file that fills it, and it is imported by the gateway at
startup — which is also what gives `app/policy/` a production consumer, so the
repo-level wiring gate stops treating it as an orphan.

The direction matters: `app/` may import `omniharness`, never the reverse.
`omniharness-harness` is a standalone distributable package, and an import back
into `app/` would make it unimportable outside this repository.
"""

from __future__ import annotations

import logging
from pathlib import Path

from omniharness.agents.middlewares.policy_hook import register_policy_middleware_builder

from .audit import PolicyAuditLog
from .config import ConfigLoader
from .disclose import DisclosureLedger
from .middleware import PolicyMiddleware
from .pending import PendingStore

logger = logging.getLogger(__name__)

#: Rules that ship with this module. Resolved HERE rather than in the harness's
#: PolicyConfig, because `omniharness-harness` is a standalone package that must
#: not import `app` — a boundary an existing gate enforces
#: (tests/test_harness_boundary.py), and which caught this when the resolution
#: was first written on the config object.
DEFAULT_RULES = Path(__file__).parent / "default_rules.yaml"


def resolve_rules_path(policy) -> Path:
    """The rules file to load.

    Falls back to the packaged defaults ONLY when no path is configured. A
    configured path that cannot be read is NOT replaced by the defaults: that
    would silently run a different policy than the operator wrote, and FR-009
    already makes an unreadable file safe by classifying everything Tier 3.
    """
    configured = getattr(policy, "rules_path", "") or ""
    return Path(configured) if configured else DEFAULT_RULES


def build(app_config) -> PolicyMiddleware | None:
    """Construct the policy middleware for one agent, or None when disabled.

    Disabled means NO middleware rather than a permissive one. FR-009 makes an
    unclassified tool Tier 3, so a half-configured policy layer would ask about
    everything — correct once the feature is deliberately on, and a poor
    surprise if it switched itself on because a config file was copied.
    """
    policy = getattr(app_config, "policy", None)
    if not getattr(policy, "enabled", False):
        return None

    state = Path(policy.state_dir)
    return PolicyMiddleware(
        loader=ConfigLoader(path=resolve_rules_path(policy)),
        pending=PendingStore(directory=state / "pending"),
        ledger=DisclosureLedger(),
        audit=PolicyAuditLog(path=state / "audit.jsonl", actor="default"),
    )


def install() -> None:
    """Called once at gateway startup."""
    register_policy_middleware_builder(build)
    logger.info("permission policy layer registered at the tool-dispatch chokepoint")
