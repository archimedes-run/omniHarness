"""Registration point for a permission policy middleware.

WHY A HOOK RATHER THAN AN IMPORT. The policy layer lives in `app/policy/` — it
belongs to the application, not the harness. `omniharness-harness` is a
standalone distributable package with its own dependency list, and nothing in it
imports from `app/`. An import here would invert that and make the harness
unimportable outside this repository.

So the harness owns the SEAM and the application fills it. The harness knows
that a policy middleware may exist and where in the chain it goes; it knows
nothing about tiers, rules, or confirmation.

This mirrors how the project already handles extension points — config-loaded
`use:` paths, MCP tool interceptors — rather than inventing a new mechanism.

REGISTERING IS NOT OPTIONAL FOR THE PRODUCT. `app/` registers at gateway
startup. If nothing registers, agents run with no policy layer, which is the
correct behaviour for a bare library consumer and would be a defect in the
gateway. The repo-level wiring gate is what notices if the registration is ever
dropped.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

#: Set by the application at startup. Takes the resolved AppConfig, returns a
#: middleware or None.
_builder: Callable[[Any], Any] | None = None


def register_policy_middleware_builder(builder: Callable[[Any], Any] | None) -> None:
    """Install the application's policy middleware factory."""
    global _builder
    _builder = builder
    logger.info("policy middleware builder %s", "registered" if builder else "cleared")


def build_policy_middleware(app_config: Any):
    """The middleware for this agent, or None.

    Returns None rather than raising when the builder fails. Note the direction:
    None means NO GATE and a logged error, not a gate that permits everything. A
    broken policy layer must not silently become one that looks like protection.
    """
    if _builder is None:
        return None
    try:
        return _builder(app_config)
    except Exception:  # noqa: BLE001 — see the docstring
        logger.exception("the permission policy middleware failed to build; agents run WITHOUT it")
        return None
