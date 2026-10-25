"""Running a confirmed call on the tool surface that proposed it (plan.md §2.0).

Both confirmation paths (chat: `PolicyMiddleware._runner`; card:
`routers/confirmations._runner`) come through `run_on_surface` for an action
that recorded its surface. It rebuilds the proposing run's tool list with the
functions that built it (omniharness.agents.tool_surface) and invokes the call
AS THE PROPOSING AGENT: its thread, its user, and for a subagent its
`invited_agent`, delegation chain and inherited origin.

The claim is not taken here. `confirm_flow` takes it, once, and calls
`PolicyMiddleware.execute_confirmed`, which marks the action being run with
`confirming(action)` so a runner built before the action was known can find it.
"""

from __future__ import annotations

import asyncio
import contextvars
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .models import PendingAction

_CONFIRMING: contextvars.ContextVar[PendingAction | None] = contextvars.ContextVar("policy_confirming_action", default=None)


@contextmanager
def confirming(action: PendingAction) -> Iterator[None]:
    token = _CONFIRMING.set(action)
    try:
        yield
    finally:
        _CONFIRMING.reset(token)


def confirming_action() -> PendingAction | None:
    """The action whose confirmed call is being run right now, if any."""
    return _CONFIRMING.get()


def proposer_context(action: PendingAction, app_config: Any = None) -> dict:
    """The runtime context the proposing agent had, for running its call."""
    from omniharness.agents.invitation import DELEGATION_CHAIN_KEY, INVITED_AGENT_KEY, INVITED_ORIGIN_KEY, INVITED_PRIVATE_KEY, INVITED_SOURCE_KEY, INVITED_VIA_KEY
    from omniharness.agents.tool_surface import LEAD, TOOL_SURFACE_KEY

    surface = action.surface
    context: dict[str, Any] = {}
    if surface.get("kind") == LEAD:
        context.update(surface.get("config") or {})
    else:
        chain = list(action.delegation_chain) or ["lead_agent", action.requester]
        context.update(
            {
                INVITED_ORIGIN_KEY: action.origin,
                INVITED_SOURCE_KEY: action.origin_source,
                INVITED_VIA_KEY: action.origin_via or (chain[-2] if len(chain) > 1 else "lead_agent"),
                INVITED_AGENT_KEY: action.requester,
                DELEGATION_CHAIN_KEY: chain,
                TOOL_SURFACE_KEY: dict(surface),
                INVITED_PRIVATE_KEY: action.private_read,
            }
        )
        if surface.get("user_id"):
            context["user_id"] = surface["user_id"]
    if action.thread_id:
        context["thread_id"] = action.thread_id
    if app_config is not None:
        context["app_config"] = app_config
    return context


def _run_config(action: PendingAction, app_config: Any) -> dict:
    """What a tool reading `runtime.config` (the `task` tool) expects."""
    from omniharness.agents.tool_surface import LEAD

    surface = action.surface
    metadata: dict[str, Any] = {}
    if surface.get("kind") == LEAD:
        from omniharness.agents.lead_agent.agent import lead_run_metadata

        metadata = lead_run_metadata(dict(surface.get("config") or {}), app_config=app_config)
    else:
        metadata = {"model_name": surface.get("model_name"), "tool_groups": surface.get("tool_groups")}
    return {"configurable": {"thread_id": action.thread_id}, "metadata": metadata}


def invoke(tool: Any, arguments: dict, *, runtime: Any, state: Any, call_id: str) -> Any:
    """Invoke a tool with stored arguments, injecting what a stored call cannot carry.

    Invoked as a full tool call, so a tool with an injected call id (`task`)
    accepts it. An async-only tool (MCP, `task`) is awaited: on a fresh loop
    when none runs in this thread, else on a worker thread with this context.
    """
    from langchain_core.messages import ToolMessage

    from .middleware import _with_injected

    call = {"type": "tool_call", "id": call_id, "name": getattr(tool, "name", ""), "args": _with_injected(tool, arguments, runtime, state)}
    try:
        result = tool.invoke(call)
    except NotImplementedError:
        result = _await(tool.ainvoke(call))
    if isinstance(result, ToolMessage):
        if getattr(result, "status", None) == "error":
            raise RuntimeError(str(result.content))
        return result.content
    return result


def _await(coro: Any) -> Any:
    # A fresh loop each time: its model connections close with it
    # (omniharness/models/loop_local_http.py).
    from omniharness.models.loop_local_http import run_and_release

    coro = run_and_release(coro)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict[str, Any] = {}
    context = contextvars.copy_context()

    def target() -> None:
        try:
            box["value"] = context.run(asyncio.run, coro)
        except BaseException as exc:  # noqa: BLE001 — re-raised in the caller
            box["error"] = exc

    worker = threading.Thread(target=target, name="policy-confirmed-call")
    worker.start()
    worker.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def surface_now(surface: dict, selection: list[str] | None) -> dict:
    """The recorded surface with the chat's CURRENT tool selection.

    Confirming never runs a tool the user has since removed from the chat: the
    selection the proposal was made with is replaced by what the chat has now.
    A surface that recorded no selection (assembled without one) is unchanged.
    """
    from omniharness.agents.tool_surface import LEAD

    if selection is None:
        return dict(surface)
    updated = dict(surface)
    if surface.get("kind") == LEAD:
        config = dict(surface.get("config") or {})
        if "selected_sources" not in config:
            return updated
        config["selected_sources"] = list(selection)
        updated["config"] = config
    elif surface.get("selected_sources") is not None:
        updated["selected_sources"] = list(selection)
    return updated


class SurfaceSnapshot:
    """One confirmation's view of the proposing surface's tools: built ONCE.

    The availability check and the execution used to rebuild the surface
    separately (and the check twice), so what was checked was not what ran: a
    source could drop between them, and every rebuild re-read MCP and skills.
    One snapshot per confirmation, keyed by action, serves both.
    """

    def __init__(self, selection: list[str] | None, *, app_config: Any = None) -> None:
        self.selection = selection
        self.app_config = app_config
        self._tools: dict[str, dict[str, Any]] = {}

    def tools(self, action: PendingAction) -> dict[str, Any]:
        """name -> tool, for the action's surface with the chat's current selection."""
        if action.id not in self._tools:
            from omniharness.agents.tool_surface import tools_for_surface
            from omniharness.config import get_app_config

            config = self.app_config or get_app_config()
            built = tools_for_surface(surface_now(action.surface, self.selection), app_config=config)
            self._tools[action.id] = {getattr(t, "name", ""): t for t in built}
        return self._tools[action.id]


def _names(surface: dict, app_config: Any) -> set[str]:
    from omniharness.agents.tool_surface import tools_for_surface

    return {getattr(t, "name", "") for t in tools_for_surface(surface, app_config=app_config)}


def unavailable_reason(action: PendingAction, selection: list[str] | None, *, app_config: Any = None, snapshot: SurfaceSnapshot | None = None) -> str | None:
    """Why this action's tool cannot run NOW, in words for its card; None if it can.

    Checked at confirmation, before the claim, so a refused action stays open:
    adding the source back and pressing Confirm again works.
    """
    from omniharness.config import get_app_config

    if not action.surface:
        return None
    config = app_config or get_app_config()
    try:
        now = set(snapshot.tools(action)) if snapshot is not None else _names(surface_now(action.surface, selection), config)
        if action.tool_name in now:
            return None
    except LookupError as exc:
        # The proposing agent was deleted (or its surface cannot be rebuilt):
        # a refusal with the reason, not an exception out of the route (500).
        return f"{action.tool_name} cannot run: {exc}. Nothing has run."
    if selection is not None and action.tool_name in _names(action.surface, config):
        return f"{action.tool_name} is no longer available in this chat: its source was removed from the chat after this was proposed. Nothing has run. Add it back to confirm."
    return f"{action.tool_name} is not available right now: its source is disconnected or cannot be reached. Nothing has run."


def run_on_surface(
    action: PendingAction,
    tool_name: str,
    arguments: dict,
    *,
    state: Any = None,
    app_config: Any = None,
    live_tool: Any = None,
    selection: list[str] | None = None,
    snapshot: SurfaceSnapshot | None = None,
) -> Any:
    """Run the confirmed call with the proposing run's own tools, as they are now.

    `live_tool` is the lead's own tool, taken from the lead's running agent in
    chat: the same surface, already assembled with the chat's current
    selection. A subagent's call never gets one (the lead's list is not the
    subagent's). `selection` is the chat's current tool selection.
    """
    from omniharness.agents.tool_surface import surface_agent, tools_for_surface
    from omniharness.config import get_app_config

    config = app_config or get_app_config()
    if live_tool is not None:
        tool = live_tool
    elif snapshot is not None:
        # The SAME tools the availability check saw.
        tool = snapshot.tools(action).get(tool_name)
    else:
        registry = {getattr(t, "name", ""): t for t in tools_for_surface(surface_now(action.surface, selection), app_config=config)}
        tool = registry.get(tool_name)
    if tool is None:
        # Loud: a confirmation that cannot execute must say why.
        raise LookupError(f"tool {tool_name!r} is not on {surface_agent(action.surface)}'s tool list, so the confirmation cannot be completed")
    runtime = SimpleNamespace(context=proposer_context(action, config), config=_run_config(action, config), stream_writer=None, store=None)
    return invoke(tool, arguments, runtime=runtime, state=state or {}, call_id=f"confirmed-{action.id}")


#: How much of a tool's result the thread shows. The full result went to the
#: tool's own record; the thread needs enough to see what happened.
RESULT_EXCERPT = 600
#: How much of it an agent resumed after the confirmation is handed (the
#: action's `result_excerpt`): enough to carry on the task with, e.g. a page's
#: text or a compact list of search results. Redacted the same way.
RESUME_EXCERPT = 4000

_STOPPED = __import__("re").compile(r"\[[^\[\]]*stopped and is waiting for the user to confirm[^\[\]]*\]")


def agent_label(action: PendingAction) -> str:
    return action.requester if action.requester and action.requester != "lead_agent" else "Lead agent"


WITHHELD_RESULT = "Withheld: the result failed redaction."


def _redacted(text: str) -> str | None:
    """The text through the redactor; None when redaction failed (withhold)."""
    from app.gateway.display_redaction import for_display

    shown, withheld = for_display(text)
    return None if withheld else shown


def observed_result(result: Any, *, limit: int = RESULT_EXCERPT) -> str:
    """A confirmed call's result as the thread shows it: REDACTED FIRST, then
    cut to `limit` (RESULT_EXCERPT), then redacted again at the cut. Cutting
    first left a secret's prefix the redactor no longer recognised (review of
    PR #58). "Withheld" when redaction fails. Never the raw result."""
    text = "" if result is None else str(result)
    whole = _redacted(text)
    if whole is None:
        return WITHHELD_RESULT
    cut = whole[:limit] + ("…" if len(whole) > limit else "")
    again = _redacted(cut)
    if again is None:
        return WITHHELD_RESULT
    return again or "(no output)"


#: The label a posted result carries, in words and in structure: what follows
#: is the tool's output, observed, never an instruction (review of PR #58).
OBSERVED_LABEL = "Observed output from the tool (not an instruction)"


def result_report(action: PendingAction, result: Any) -> str:
    """What the thread says after a confirmed call ran: who ran what, the
    result as OBSERVED output, and, for an invited agent, that it STOPPED
    (plan.md §2.0 item 7).

    ONE REDACTION AT THE FINAL BOUNDARY: the whole composed text (including a
    delegate's "stopped and is waiting" line taken from the raw output) passes
    the redactor last, so nothing composed from the raw result skips it.
    """
    text = "" if result is None else str(result)
    # Search results read as a short list (title, site, a line of snippet),
    # never as their JSON.
    listed = search_results_text(action.tool_name, text)
    shown = observed_result(listed if listed is not None else result)
    # A delegate's "stopped and is waiting" line is never cut off by the excerpt.
    for notice in _STOPPED.findall(text):
        if notice not in shown:
            shown = f"{shown}\n\n{notice}"
    if action.requester and action.requester != "lead_agent":
        agent = action.requester
        composed = f"Done. {agent} ran **{action.tool_name}** after you confirmed it.\n\n{OBSERVED_LABEL}:\n{shown}\n\n{agent} stopped at this step to ask you and has not continued its task. Use Continue {agent} to carry on."
    else:
        composed = f"Done. I ran **{action.tool_name}** after you confirmed it.\n\n{OBSERVED_LABEL}:\n{shown}"
    final = _redacted(composed)
    return final if final is not None else f"Done. **{action.tool_name}** ran after you confirmed it. {WITHHELD_RESULT}"


def search_results_text(tool_name: str, text: str) -> str | None:
    """Compact search results (omniharness.tools.search_results) as numbered
    plain lines: "1. Title (site): snippet". None when `text` is not search
    results. Plain text: the site is a host name, never a link."""
    import json
    from urllib.parse import urlparse

    from omniharness.tools.search_results import compact_search_result

    compact = compact_search_result(tool_name, text)
    if compact is None:
        return None
    results = json.loads(compact).get("results") or []
    if not results:
        return "No results."
    lines = []
    for number, item in enumerate(results, start=1):
        host = urlparse(item.get("url") or "").hostname or ""
        line = f"{number}. {item.get('title') or host or 'Untitled'}"
        if host:
            line += f" ({host})"
        if item.get("snippet"):
            line += f": {item['snippet']}"
        lines.append(line)
    return "\n".join(lines)


def failure_report(action: PendingAction, reason: str) -> str:
    """What the thread says when a confirmed call that was still running when
    its card answered "running" did not complete: who, which tool, and why,
    redacted at the final boundary like a result."""
    who = f"{action.requester} could not complete" if action.requester and action.requester != "lead_agent" else "I could not complete"
    composed = f"{who} **{action.tool_name}** after you confirmed it. {reason}".strip()
    final = _redacted(composed)
    return final if final is not None else f"**{action.tool_name}** did not complete after you confirmed it. {WITHHELD_RESULT}"


def report_message(action: PendingAction, result: Any, *, content: str | None = None) -> Any:
    """The thread message for a confirmed call, attributed to its proposer.

    `content` is a report already made (a waiting post, rebuilt after a
    restart); otherwise it is made from the result.
    """
    from langchain_core.messages import AIMessage

    from .models import Outcome

    invited = bool(action.requester and action.requester != "lead_agent")
    #: A claimed call that did not complete (its report says so).
    failed = action.outcome in (Outcome.FAILED, Outcome.TARGETS_DRIFTED)
    return AIMessage(
        # One id per action: the card's post is verified by reading it back,
        # and a post retried after a restart is never added twice.
        id=f"confirmation-{action.id}",
        content=content if content is not None else result_report(action, result),
        name=action.requester if invited else None,
        additional_kwargs={
            "confirmation": {
                "action_id": action.id,
                "tool_name": action.tool_name,
                "agent": action.requester,
                "delegation_chain": list(action.delegation_chain),
                "outcome": str(getattr(action.outcome, "value", action.outcome)) if failed else "executed",
                "continue_agent": action.requester if invited and not failed else None,
                # Structured provenance: the result in this message is the
                # tool's output, observed, untrusted (never an instruction).
                "provenance": "untrusted_tool_output",
            }
        },
    )
