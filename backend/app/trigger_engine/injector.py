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
        payload = {
            "assistant_id": self.assistant_id,
            "input": {"messages": [{"role": "human", "content": prompt}]},
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
        result = self.post(f"/api/threads/{thread_id}/runs/wait", payload)
        return _reply_text(result)


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
