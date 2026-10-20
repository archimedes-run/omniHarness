"""Turn injection — the load-bearing mechanism (FR-007, FR-009, FR-010, FR-011).

A firing is *just a turn*. Reusing the turn contract is what gives a trigger the
agent's existing skills, tools and memory for free, and is why no second
execution path exists to diverge from the first.

Every parameter here was verified against a running gateway by the Phase 1
spike, which corrected three assumptions that would otherwise have surfaced in
Phase 3:

  * `assistant_id` is `lead_agent`, not `agent`
  * the tool-selection body field is `sources`, not `tool_ids`
  * the provenance marker is NOT present in the runs/wait response body — it is
    observable via GET /threads/{id}/state and /runs, so FR-009 reads it from
    the run record rather than the reply
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_ASSISTANT_ID = "lead_agent"

#: FR-009. Structural, not a content convention: a marker in the text could be
#: imitated by anything the agent echoes. This lives in the run's config and
#: metadata, where a message body cannot reach it.
PROVENANCE_KEY = "turn_provenance"
SYNTHETIC = "synthetic-trigger"
RULE_KEY = "trigger_rule_id"


class InjectionError(RuntimeError):
    pass


def is_synthetic(run_record: dict) -> bool:
    """True when a run was injected by a trigger rather than sent by the user.

    Structural (FR-009): it reads the run's own configuration, which a turn's
    content cannot influence. This is also what presence.py uses — a run WITHOUT
    the marker is a user turn — so weakening provenance would visibly break
    presence routing too.
    """
    for section in ("config", "metadata"):
        blob = run_record.get(section) or {}
        if isinstance(blob, dict):
            if blob.get(PROVENANCE_KEY) == SYNTHETIC:
                return True
            inner = blob.get("configurable")
            if isinstance(inner, dict) and inner.get(PROVENANCE_KEY) == SYNTHETIC:
                return True
    return False


@dataclass
class TurnInjector:
    """Injects a synthetic turn and returns the reply.

    `post` / `put` / `get` are the gateway HTTP verbs, injected so tests do not
    need a live server. In production they are bound to the in-process client
    carrying `create_internal_auth_headers()`.
    """

    post: Callable[[str, dict], dict]
    put: Callable[[str, dict], dict]
    get: Callable[[str], dict]
    assistant_id: str = DEFAULT_ASSISTANT_ID
    default_tools: tuple[str, ...] = field(default_factory=tuple)
    #: The messages of the last injected turn: the prompt, every tool call and
    #: result, and the reply. Read by the runner for the run history (Feature
    #: 006). The engine runs one rule at a time on one thread, so "last" is
    #: unambiguous.
    last_turn: list = field(default_factory=list)
    #: Whether `last_turn` was cut at this turn's own prompt (True), or the
    #: turn could not be told apart from the rest of the thread and nothing was
    #: kept (False). None before any turn.
    last_turn_found: bool | None = None

    def reset_turn(self) -> None:
        """Forget the last turn. The runner calls this before EVERY firing, so
        a firing that fails before injecting never carries the previous one's
        messages into its record."""
        self.last_turn = []
        self.last_turn_found = None

    def create_thread(self, rule_id: str) -> str:
        rec = self.post("/api/threads", {"metadata": {RULE_KEY: rule_id}})
        tid = rec.get("thread_id")
        if not tid:
            raise InjectionError(f"thread creation returned no id for rule {rule_id!r}")
        return tid

    def configure_tools(self, thread_id: str, sources: list[str]) -> list[str]:
        """FR-011 — a system-initiated turn has no human to attach tools by hand.

        Pinned servers are enforced server-side regardless of what we send, so
        this only has to name the extras.
        """
        rec = self.put(f"/api/threads/{thread_id}/tools", {"sources": sources})
        return rec.get("sources", [])

    def inject(self, thread_id: str, rule_id: str, prompt: str) -> str:
        """Inject the turn and return the assistant's reply text."""
        # The markers go in `configurable` and `metadata` ONLY — deliberately.
        #
        # They must also reach `config["context"]`, because that is the sole
        # container `ToolRuntime.context` is built from, and therefore the only
        # way a policy middleware's wrap_tool_call can tell a synthetic turn
        # from a real one. But do NOT add a "context" key here to achieve that:
        # build_run_config prefers `context` when a request carries both and
        # drops `configurable` wholesale, taking `thread_id` with it. The
        # gateway mirrors the whitelisted keys across instead — see
        # `_mirror_runtime_visible_keys` in app/gateway/services.py.
        marker = f"trigger-turn-{uuid.uuid4().hex}"
        payload = {
            "assistant_id": self.assistant_id,
            # The id marks where THIS turn starts in the thread runs/wait
            # returns, so the run history keeps only this turn's messages.
            "input": {"messages": [{"role": "human", "content": prompt, "id": marker}]},
            "config": {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                    PROVENANCE_KEY: SYNTHETIC,
                    RULE_KEY: rule_id,
                }
            },
            "metadata": {PROVENANCE_KEY: SYNTHETIC, RULE_KEY: rule_id},
        }
        self.reset_turn()
        result = self.post(f"/api/threads/{thread_id}/runs/wait", payload)
        turn = turn_messages(result, marker)
        self.last_turn, self.last_turn_found = (turn or [], turn is not None)
        return _reply_text(result)


def turn_messages(result: dict, marker: str | None) -> list | None:
    """This turn's messages only, from its own prompt to the end (runs/wait
    returns the whole thread), found by the message id the injector sent.

    Not by the prompt's text: a rule sends the same prompt every firing, so
    text cannot tell this turn from an earlier one. None when the id is not
    there (a summariser may have rewritten the thread): the caller stores no
    messages and says so, never the earlier turns."""
    msgs = [m for m in (result.get("messages") or []) if isinstance(m, dict)]
    if marker:
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].get("id") == marker:
                return msgs[i:]
    return None


def _reply_text(result: dict) -> str:
    msgs = result.get("messages") or []
    for msg in reversed(msgs):
        if not isinstance(msg, dict):
            continue
        if msg.get("type") in ("human", "user") or msg.get("role") in ("human", "user"):
            continue
        content: Any = msg.get("content")
        if isinstance(content, list):
            parts = [b.get("text", "") for b in content if isinstance(b, dict)]
            content = " ".join(p for p in parts if p)
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""
