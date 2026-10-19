from pydantic import BaseModel, Field, model_validator

#: Settings that live in the RULES file's `confirmation:` block, not here. A
#: config.yaml that sets one is rejected rather than ignored: an inert security
#: setting gives an operator a false belief about what they changed.
_RULES_FILE_ONLY = ("expires_after_seconds", "threshold_targets")


class PolicyConfig(BaseModel):
    """Feature flag and settings for the permission policy engine. Defaults ON.

    On, and failing closed, because Article II admits no ungated path: a fresh
    clone that ran every tool unchecked was the defect (audit P-1). With no
    rules file of your own the shipped rules apply
    (backend/app/policy/default_rules.yaml). `enabled: false` opts out.
    """

    # ON by default, in tracked code. It was False here and True only in the
    # gitignored config.yaml, so a fresh clone ran every tool ungated (Article
    # XIV; audit P-1). Off is an explicit choice.
    enabled: bool = Field(default=True, description="Classify tool calls before dispatch. On by default. `false` is the one way to run with no permission policy; when on but unbuildable, tool calls are refused.")
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

    @model_validator(mode="before")
    @classmethod
    def _reject_settings_that_live_in_the_rules_file(cls, data):
        """`expires_after_seconds` was declared here and never read: expiry came
        from the rules file, so setting it in config.yaml changed nothing
        (ROADMAP-FOLLOWUPS). Its one home is now the rules file, where
        `threshold_targets` already was, and setting it here is an error."""
        if isinstance(data, dict):
            misplaced = [key for key in _RULES_FILE_ONLY if key in data]
            if misplaced:
                raise ValueError(
                    f"policy.{', policy.'.join(misplaced)} is not read from config.yaml. Set it in the rules file's "
                    "`confirmation:` block instead (the file at policy.rules_path; by default "
                    "backend/app/policy/default_rules.yaml, which ships expires_after_seconds: 14400)."
                )
        return data
