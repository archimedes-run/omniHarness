from .features import Next, Prev, RuntimeFeatures
from .lead_agent import make_lead_agent
from .lead_agent.prompt import prime_enabled_skills_cache
from .thread_state import SandboxState, ThreadState

# LangGraph imports omniharness.agents when registering the graph. Prime the
# enabled-skills cache here so the request path can usually read a warm cache
# without forcing synchronous filesystem work during prompt module import.
prime_enabled_skills_cache()

# NOTE: `create_omniharness_agent` was REMOVED with Feature 003 (FR-003).
#
# It was a fifth agent-construction site that assembled its own middleware and
# so bypassed the policy layer entirely. Its documented middleware-takeover
# contract — `middleware=[x]` yields exactly `[x]` — is incompatible with
# Article II BY DESIGN, not by accident: you cannot guarantee both "the caller
# controls the whole middleware list" and "no path bypasses policy". The
# contract is the thing that was wrong.
#
# `RuntimeFeatures`, `Next` and `Prev` remain — `app/middlewares/truncation.py`
# uses `Prev` for middleware positioning.
#
# If an embedding API is wanted later, the correct version routes through
# policy. See backend/docs/PLATFORM_ARCHITECTURE.md.
__all__ = [
    "RuntimeFeatures",
    "Next",
    "Prev",
    "make_lead_agent",
    "SandboxState",
    "ThreadState",
]
