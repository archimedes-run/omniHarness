from pydantic import BaseModel, Field


class PolicyConfig(BaseModel):
    """Feature flag and settings for the permission policy engine. Defaults OFF.

    Off by default because turning it on changes what the assistant will do
    without asking. A gateway that has not had its classification rules written
    would treat every tool as Tier 3 (FR-009) and ask before everything —
    correct, and not what someone wants to discover by copying a config file.
    """

    enabled: bool = Field(default=False, description="Classify tool calls before dispatch. When off, no policy middleware is installed.")
    rules_path: str = Field(
        default="",
        description=(
            "Hot-reloadable classification rules (FR-007). Empty means the "
            "defaults the policy module ships. Point this at your own copy to "
            "customise; a configured path that cannot be read makes EVERY tool "
            "Tier 3 rather than silently falling back to the defaults, which "
            "would substitute a different policy for the one you wrote."
        ),
    )
    state_dir: str = Field(default=".omni-harness/policy", description="Directory for pending actions and execution records.")

    expires_after_seconds: int = Field(
        default=4 * 60 * 60,
        description=(
            "How long an unconfirmed Tier 3 action stays confirmable (FR-019). "
            "4 hours is A STARTING GUESS, not a measured value — long enough to "
            "survive a meeting, short enough that a forgotten action does not "
            "linger for days. Labelled as a guess so it does not acquire "
            "authority it has not earned (Article X)."
        ),
    )
