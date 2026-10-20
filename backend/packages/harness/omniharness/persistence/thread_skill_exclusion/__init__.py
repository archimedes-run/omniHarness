"""Per-thread skill exclusion persistence (Feature 006).

Stores which skills a conversation has REMOVED from its agent's set, by skill
name. The gateway loads it at run launch and threads it into the runtime
context as ``excluded_skills``; the lead agent subtracts it from the skills it
would otherwise have. Never taken from the client's run body.
"""

from omniharness.persistence.thread_skill_exclusion.model import ThreadSkillExclusionRow
from omniharness.persistence.thread_skill_exclusion.sql import ThreadSkillExclusionRepository

__all__ = ["ThreadSkillExclusionRow", "ThreadSkillExclusionRepository"]
