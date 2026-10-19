from pydantic import BaseModel, Field


class RemoteDeliveryConfig(BaseModel):
    """Where a proactive message goes when it goes remote: one chat on one IM
    channel. Explicit, never inferred — not "the first allowed user", not "the
    last chat that wrote in". A message sent to the wrong person is not a
    delivery problem, it is a disclosure.
    """

    channel: str = Field(default="telegram", description="An IM channel configured under `channels:` (telegram, slack, ...). It must be enabled and running.")
    chat_id: str = Field(description="The chat to deliver to. For Telegram, your numeric user id (a private chat with the bot has the same id).")


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
    rules_path: str = Field(
        default="",
        description=(
            "Hot-reloadable rule definitions. Empty means the defaults the "
            "engine ships (all rules disabled). Point this at your own file to "
            "customise; a configured path that cannot be read stops the engine "
            "rather than falling back, which would run a different rule set "
            "than you wrote."
        ),
    )
    state_dir: str = Field(default=".omni-harness/triggers", description="Directory for scheduler, fingerprint, thread-map, audit and lock files.")
    tick_seconds: float = Field(default=30.0, description="Base interval between rule evaluations. The loop sleeps to the next computed moment rather than busy-polling.")
    actor: str = Field(default="default", description="Identity the engine acts as; recorded on every audit entry (Article VIII).")
    remote: RemoteDeliveryConfig | None = Field(
        default=None,
        description=("Recipient for rules whose destination resolves to remote (`remote`, or `auto` with no local destination). Unset means remote delivery fails, recorded on each firing with the reason; it never falls back to a guess."),
    )
