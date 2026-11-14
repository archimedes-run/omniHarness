"""BuilderController port: how the chat builder's tools reach the config store (Spec 010).

The builder writes agents and skills (omniharness.config.config_versions) and
automations (app.gateway.automations_store, which the harness must not
import), so the gateway registers one implementation here at startup, as it
does for the ledger. The builder tools exist only while one is registered.

Every method is SYNCHRONOUS: a confirmed Tier 3 tool runs with a sync
`tool.invoke` (app/policy/surface_run.py). `context` is the run's runtime
context, server-set (thread_id, user_id, agent_name, ...), never the model's.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BuilderController(Protocol):
    def draft(self, context: dict, *, kind: str, name: str, fields: dict[str, Any], guessed: list[str], replace_current: bool) -> str:
        """Record a draft in this thread (never in the store); its preview or diff."""
        ...

    def read(self, context: dict, *, kind: str, name: str | None) -> str:
        """The live config of one agent, skill or automation, or a list of them."""
        ...

    def diff(self, context: dict, *, draft_id: str) -> str:
        """A draft against the live store, read now."""
        ...

    def save(self, context: dict, *, draft_id: str) -> str:
        """Save a draft (only ever run as a confirmed Tier 3 action)."""
        ...

    def grant(self, context: dict, *, agent: str, integrations: list[str], tools: list[str], autonomy: list[str], tool_groups: list[str] | None = None, skills: list[str] | None = None, model: str | None = None) -> str:
        """Widen an agent's tool access or standing grants (button-confirmed only)."""
        ...

    def undo(self, context: dict, *, kind: str, name: str, version: int) -> str:
        """Undo `version` (the current one): the version before it, as a new version (confirmed only)."""
        ...

    def precheck(self, tool_name: str, arguments: dict, context: dict) -> dict:
        """Before a save, grant or undo card is shown (app/policy/builder_cards):
        {"refused", "note", "replaces", "arguments", "origin", "button_only"}."""
        ...

    def unavailable_reason(self) -> str | None:
        """Why the builder is not offered on this install (no policy layer, or
        the rules in force do not name its tools), or None."""
        ...


_controller: BuilderController | None = None


def get_builder_controller() -> BuilderController | None:
    return _controller


def set_builder_controller(controller: BuilderController | None) -> None:
    global _controller
    _controller = controller
