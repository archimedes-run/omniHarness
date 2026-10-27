"""VerificationMiddleware: the lead's final reply carries the server's
verification record, and no trailing menu (spec 009 FR-052, FR-056).

Runs in ``after_model`` when the model gives its final reply (no tool calls).
It is placed BEFORE TodoMiddleware in the middleware list, so its hook runs
AFTER TodoMiddleware's (after_model hooks run in reverse order): when the todo
gate sends the model back, this hook does not run for that message.

1. Trailing menu (owner rule, FR-056): a last paragraph that offers options or
   asks "Would you like me to...?" is removed when enough of the reply stays
   to stand on its own. A reply that is only a question is left alone.
2. Verification record (FR-052): the final message gets
   ``additional_kwargs[VERIFICATION_KEY]``, built from this turn's tool
   results and checklist (working_loop.build_verification_record), never from
   the reply's claims. The chat shows it as a Verified/Unverified badge; the
   per-run trace and the eval read it.

The record is display and measurement data. No policy decision reads it.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from omniharness.agents.thread_state import ThreadState
from omniharness.agents.working_loop import VERIFICATION_KEY, build_verification_record, strip_trailing_menu, text_of

logger = logging.getLogger(__name__)

#: How the policy layer opens its appended Tier 2 disclosure (disclose.py).
DISCLOSURE_HEADING = "\n\nAlso, for the record:"


def _replace_text(message: AIMessage, text: str) -> Any:
    content = message.content
    if isinstance(content, str):
        return text
    if isinstance(content, list):
        # Keep non-text blocks (reasoning, images); the text becomes one block.
        others = [b for b in content if not (isinstance(b, dict) and b.get("type") == "text") and not isinstance(b, str)]
        return [*others, {"type": "text", "text": text}]
    return text


class VerificationMiddleware(AgentMiddleware):
    """Attaches the verification record to the lead's final reply."""

    state_schema = ThreadState

    def _apply(self, state: dict[str, Any], runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        if not messages or not isinstance(messages[-1], AIMessage):
            return None
        last = messages[-1]
        if last.tool_calls:
            return None
        reply = text_of(last)
        fixes: list[str] = []
        # The policy layer's Tier 2 disclosure block (app/policy/disclose.py)
        # is appended after the model's text and is never touched: the menu
        # rule applies to the model's part above it.
        body, sep, disclosure = reply.partition(DISCLOSURE_HEADING)
        new_body, changed = strip_trailing_menu(body)
        if changed:
            fixes.append("trailing_menu_removed")
            reply = new_body + (("\n\n" + sep.strip() + disclosure) if sep else "")
        context = getattr(runtime, "context", None) or {}
        run_id = context.get("run_id") if isinstance(context, dict) else None
        try:
            record = build_verification_record(messages, state.get("todos") or [], run_id=run_id, reply=reply)
        except Exception:  # noqa: BLE001 - a record that cannot be built is left out, never invented
            logger.warning("verification record could not be built", exc_info=True)
            return None
        if fixes:
            record["style_fixes"] = fixes
        kwargs = {**(last.additional_kwargs or {}), VERIFICATION_KEY: record}
        update: dict[str, Any] = {"additional_kwargs": kwargs}
        if changed:
            update["content"] = _replace_text(last, reply)
        out: dict[str, Any] = {"messages": [last.model_copy(update=update)]}
        if last.id:
            out["verifications"] = {last.id: record}
        return out

    def after_model(self, state: dict[str, Any], runtime: Runtime) -> dict[str, Any] | None:
        return self._apply(state, runtime)

    async def aafter_model(self, state: dict[str, Any], runtime: Runtime) -> dict[str, Any] | None:
        return self._apply(state, runtime)
