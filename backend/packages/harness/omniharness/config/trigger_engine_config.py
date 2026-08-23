from pydantic import BaseModel, Field


class TriggerEngineConfig(BaseModel):
    """Feature flag and settings for the Feature 002 trigger engine. Defaults OFF.

    Off by default because the engine speaks without being asked. A gateway
    process that should not be sending proactive messages — a CI run, a
    developer's laptop reproducing a bug, a second deployment sharing a
    database — should not start one because a config file was copied.

    Note that `enabled` is not a substitute for single-runner election: the
    engine runs under `uvicorn --workers N`, and enabling it enables it in every
    worker. Election is what makes that safe (see trigger_engine/election.py);
    this flag decides whether any worker runs it at all.
    """

    enabled: bool = Field(default=False, description="Start the trigger engine in this gateway process (subject to single-runner election).")
    rules_path: str = Field(default=".omni-harness/triggers/rules.json", description="Hot-reloadable rule definitions.")
    state_dir: str = Field(default=".omni-harness/triggers", description="Directory for scheduler, fingerprint, thread-map, audit and lock files.")
    tick_seconds: float = Field(default=30.0, description="Base interval between rule evaluations. The loop sleeps to the next computed moment rather than busy-polling.")
    actor: str = Field(default="default", description="Identity the engine acts as; recorded on every audit entry (Article VIII).")
