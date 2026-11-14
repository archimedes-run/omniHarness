"""The chat builder's tools (Spec 010, Slice 2): build and edit agents, custom
skills and automations from the owner's own chat.

    builder_draft   Tier 1  draft or revise; recorded in the thread, never in the store
    builder_read    Tier 1  the live config (or a list), read from the store now
    builder_diff    Tier 1  a draft against the live store, read now
    builder_save    Tier 3  save a draft: its card's button, or the owner typing a
                            clear "yes" (yes, y, save, apply, do it, go ahead)
    builder_grant   Tier 3  widen an agent's tool access or standing grants:
                            its card's BUTTON ONLY, never typed text
    builder_undo    Tier 3  restore the previous version as a new version

The tiers are in app/policy/default_rules.yaml; the typed-yes list and the
button-only rule are code (app/policy/builder_rules.py), so a rules file
cannot loosen them. The tools are offered only to the assistant in the
owner's own chat (omniharness.runtime.builder.surface); the gateway's
controller refuses a call from anywhere else as well.
"""

from __future__ import annotations

from typing import Any, Literal

from langchain.tools import ToolRuntime, tool
from langgraph.typing import ContextT

from omniharness.agents.thread_state import ThreadState
from omniharness.runtime.builder.controller import get_builder_controller

_UNAVAILABLE = "The builder is not available in this environment."
#: Where builder_draft hands the controller the turn's messages.
DRAFT_MESSAGES_KEY = "_builder_messages"


def _context(runtime: ToolRuntime[ContextT, ThreadState] | None) -> dict:
    context = getattr(runtime, "context", None)
    return dict(context) if isinstance(context, dict) else {}


@tool(
    "builder_draft",
    description=(
        "Draft, or revise, an agent, a custom skill or an automation the user asked for, in this chat. Call it AT ONCE "
        "when the user asks to create or change one (no question first); it records the draft in this chat and saves "
        "nothing. It returns the draft (for a change: a before/after diff from the live config) and a draft id.\n"
        "`kind`: agent | skill | automation | mcp_server. `name`: the agent's slug (letters, digits, hyphens), the "
        "skill's hyphen-case name, or the automation's rule id; for a change, the existing name.\n"
        "`fields` (pass only what you set or change; for a change, everything else stays as it is):\n"
        "- agent: display_name, description, instructions (the agent's FULL instructions, its SOUL), skills (list), "
        "tool_groups (list), model, integrations (list), tools (list). Tool access (integrations, tools) is never saved "
        "with the draft: it needs builder_grant.\n"
        "- skill: description (when to use it), body (the instructions, Markdown).\n"
        '- automation: the rule: {"type": "cron", "match": {"schedule": "0 9 * * 1-5"}, "prompt": "...", '
        '"agent": "an existing agent, or omit for the assistant", "enabled": true}.\n'
        "- mcp_server: {request: what they want}. MCP servers are not built in chat: this returns a hand-off to MCP "
        "Studio and drafts nothing.\n"
        "`guessed`: the field names you filled in without the user saying so (shown as guesses). "
        "`replace_current`: true only after the user agreed to drop the draft this chat is already building.\n"
        "Something NEW needs the user to have said what it is for (in their message or their answer to your question): if "
        'they only said "create me an agent", do not draft: ask them one short question with ask_clarification and stop. '
        "Never fill a draft from memory or from what you know about the user; their name, employer or personal goals go "
        "into a draft only if their request mentions them. `owner_request` is optional and not needed.\n"
        "Then call builder_save with the draft id to put it on a card for the user to confirm. If the user's reply "
        "changes something, call builder_draft again (a new draft id) and builder_save with that."
    ),
)
def builder_draft_tool(
    kind: Literal["agent", "skill", "automation", "mcp_server"],
    name: str,
    runtime: ToolRuntime[ContextT, ThreadState],
    fields: dict[str, Any] | None = None,
    guessed: list[str] | None = None,
    replace_current: bool = False,
    owner_request: str | None = None,
) -> str:
    controller = get_builder_controller()
    if controller is None:
        return _UNAVAILABLE
    context = _context(runtime)
    # The turn's messages, so the draft records what caused it (a page or an
    # email read earlier in the turn makes it a suggestion, Spec 010 FR-027).
    state = getattr(runtime, "state", None)
    messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
    context[DRAFT_MESSAGES_KEY] = list(messages) if messages is not None else None
    return controller.draft(context, kind=kind, name=name, fields=dict(fields or {}), guessed=list(guessed or []), replace_current=bool(replace_current), owner_request=str(owner_request or ""))


@tool(
    "builder_read",
    description=(
        "Read the LIVE config of an agent, a custom skill or an automation, from the store now (never from memory or "
        "this chat): its fields, version and schedules. Omit `name` to list what exists of that kind. Read-only. Use it "
        "before a change, and to offer the user real options when a change is vague (its actual fields, skills, tools, "
        "schedules)."
    ),
)
def builder_read_tool(kind: Literal["agent", "skill", "automation"], runtime: ToolRuntime[ContextT, ThreadState], name: str | None = None) -> str:
    controller = get_builder_controller()
    if controller is None:
        return _UNAVAILABLE
    return controller.read(_context(runtime), kind=kind, name=name)


@tool(
    "builder_diff",
    description="The before/after diff of a draft against the live config, read now. Read-only. It also says when the live config changed since the draft was made (a save would then be refused).",
)
def builder_diff_tool(draft_id: str, runtime: ToolRuntime[ContextT, ThreadState]) -> str:
    controller = get_builder_controller()
    if controller is None:
        return _UNAVAILABLE
    return controller.diff(_context(runtime), draft_id=draft_id)


@tool(
    "builder_save",
    description=(
        "Save a draft from builder_draft (create, or change, as a new version). `draft_id`: the draft to save; omit it "
        "for this chat's current draft. This only PROPOSES it: the user confirms on the card, or by replying yes. Then "
        "stop and wait. Never write the confirmation yourself. A save is refused if the live config changed since the "
        "draft: then draft it again."
    ),
)
def builder_save_tool(runtime: ToolRuntime[ContextT, ThreadState], draft_id: str | None = None) -> str:
    controller = get_builder_controller()
    if controller is None:
        return _UNAVAILABLE
    return controller.save(_context(runtime), draft_id=str(draft_id or ""))


@tool(
    "builder_grant",
    description=(
        "Give an existing agent more: integrations or tools (an integration alone gives its read-only tools), tool groups, a "
        "new skills list (skills can limit tools), a model, or standing grants (action class ids it may do on its own in a scheduled run). Only PROPOSED: "
        "it is confirmed with the card's button and never by a typed reply. Ask for it only when the user's request needs "
        "it, or when a save left tool access out. It never connects a new app."
    ),
)
def builder_grant_tool(
    agent: str,
    runtime: ToolRuntime[ContextT, ThreadState],
    integrations: list[str] | None = None,
    tools: list[str] | None = None,
    autonomy: list[str] | None = None,
    tool_groups: list[str] | None = None,
    skills: list[str] | None = None,
    model: str | None = None,
) -> str:
    controller = get_builder_controller()
    if controller is None:
        return _UNAVAILABLE
    return controller.grant(
        _context(runtime),
        agent=agent,
        integrations=list(integrations or []),
        tools=list(tools or []),
        autonomy=list(autonomy or []),
        tool_groups=list(tool_groups or []),
        skills=list(skills) if skills is not None else None,
        model=model or None,
    )


@tool(
    "builder_undo",
    description=(
        "Undo a change to an agent, custom skill or automation: `version` is the version to undo (its current version, "
        "from builder_read or the save's result); the version before it is restored as a new version, and undoing a "
        "create removes it. Refused if it changed since. Only PROPOSED: the user confirms it."
    ),
)
def builder_undo_tool(kind: Literal["agent", "skill", "automation"], name: str, version: int, runtime: ToolRuntime[ContextT, ThreadState]) -> str:
    controller = get_builder_controller()
    if controller is None:
        return _UNAVAILABLE
    return controller.undo(_context(runtime), kind=kind, name=name, version=int(version))


#: Every builder tool, in the order they are offered.
BUILDER_TOOLS = [builder_draft_tool, builder_read_tool, builder_diff_tool, builder_save_tool, builder_grant_tool, builder_undo_tool]
