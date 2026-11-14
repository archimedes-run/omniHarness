"""Where the chat builder may run, and what it may never target (Spec 010 FR-029, FR-030, FR-031).

ONE decision, read in two places: the lead's tool assembly (the tools are not
offered at all) and the builder itself at dispatch (a call that reaches it from
anywhere else is refused). Both read the run's runtime context, which the
server sets; nothing the model or a page writes can reach it.

The builder belongs to the OWNER'S OWN CHAT with the assistant:

- not a scheduled run, a workflow run, a run resumed after a confirmation,
  a "Continue <agent>" turn or a turn handed to an @-called agent (nobody is
  asking, or someone else is answering);
- not a delegated subagent or any invited agent (its "user" is its inviter);
- not a custom agent's own chat: an agent never holds builder tools, so it can
  never change itself (FR-031, decided default Q5). A request to change it is
  made in the assistant's chat or in Studio.

The bootstrap flow (a new agent's first conversation, or the channel
`/bootstrap` command) is the owner's own chat too: there the builder replaces
`setup_agent`, and may target only the agent being set up.
"""

from __future__ import annotations

from omniharness.agents.called_agents import CALLED_AGENT_KEY, RESUME_ACTION_KEY
from omniharness.agents.invitation import DELEGATION_CHAIN_KEY, INVITED_AGENT_KEY, INVITED_ORIGIN_KEY

#: Server-set markers of a run that is not the owner talking to the assistant.
#: "continue_action" is set by the gateway for "Continue <agent>"
#: (app.gateway.services.CONTINUE_ACTION_KEY); the trigger keys by Feature 002
#: (app.policy.provenance); "workflow_run_id" by the workflow runner.
NOT_THE_OWNERS_CHAT_KEYS: tuple[str, ...] = (
    CALLED_AGENT_KEY,
    RESUME_ACTION_KEY,
    "continue_action",
    "trigger_rule_id",
    "trigger_firing_id",
    "workflow_run_id",
    INVITED_AGENT_KEY,
    DELEGATION_CHAIN_KEY,
)

#: The default assistant's own entity in the versioned store.
LEAD_AGENT = "lead_agent"


#: The builder tools a run resumed on the owner's Question-card answer may
#: use (spec 010): the answer to the builder's own "what should it do?" can
#: become a draft and its save CARD; nothing in that run writes.
QUESTION_RESUME_TOOLS = frozenset({"builder_draft", "builder_save"})


def question_resume(context: dict | None) -> bool:
    """This run is the lead resumed on Question-card answers only (no card
    outcomes in it)."""
    record = (context or {}).get(RESUME_ACTION_KEY)
    return isinstance(record, dict) and bool(record.get("question_ids")) and not record.get("ids")


def builder_refusal(context: dict | None, tool: str | None = None) -> str | None:
    """None when this run may use the builder (or `tool` of it); otherwise
    why not, in words."""
    ctx = context or {}
    if tool in QUESTION_RESUME_TOOLS and question_resume(ctx):
        ctx = {k: v for k, v in ctx.items() if k != RESUME_ACTION_KEY}
    if ctx.get("turn_provenance") == "synthetic-trigger" or any(ctx.get(key) for key in NOT_THE_OWNERS_CHAT_KEYS) or INVITED_ORIGIN_KEY in ctx:
        return "Agents, skills and automations can only be built or changed from your own chat with the assistant, not from a scheduled, delegated, resumed or @-called run."
    if ctx.get("agent_name") and not ctx.get("is_bootstrap"):
        return f"I am the agent {ctx['agent_name']!r}, and an agent cannot change itself or other agents. Ask the assistant in a new chat, or open Agent Studio."
    return None


def bootstrap_target(context: dict | None) -> str | None:
    """In the bootstrap flow, the one agent it may write; else None."""
    ctx = context or {}
    if not ctx.get("is_bootstrap"):
        return None
    name = ctx.get("agent_name")
    return str(name).lower() if isinstance(name, str) and name else LEAD_AGENT


def forbidden_targets(context: dict | None) -> set[str]:
    """Agents this run may never propose, save or grant a change to (FR-030):
    itself and every agent in its call chain. The assistant itself counts
    ("lead_agent"): it never edits its own instructions from chat, except in
    the bootstrap flow, which exists to write them."""
    ctx = context or {}
    out: set[str] = set()
    for key in ("agent_name", INVITED_AGENT_KEY, CALLED_AGENT_KEY):
        value = ctx.get(key)
        if isinstance(value, str) and value:
            out.add(value.lower())
    for member in ctx.get(DELEGATION_CHAIN_KEY) or ():
        if isinstance(member, str) and member:
            out.add(member.lower())
    out.add(LEAD_AGENT)
    allowed = bootstrap_target(ctx)
    if allowed is not None:
        out.discard(allowed)
    return out


#: The start of builder_draft's refusal when a NEW agent, skill or automation
#: was asked for without saying what it is for ("create me an agent"): the
#: lead asks one question instead (clarification_middleware lets that question
#: through; it is not a mid-task question).
ASK_FIRST_PREFIX = "Nothing was drafted: the request does not say what"

#: Builder cards whose decline or expiry ends the build for that turn: the
#: resumed lead acknowledges briefly and stops (working_loop).
BUILDER_CARD_TOOLS = frozenset({"builder_save", "builder_grant", "builder_undo"})

#: The resumed lead's whole reply after a builder card was declined or expired
#: (and nothing it asked for ran).
DECLINED_ACK = "Okay, not saved. The draft is kept in this chat: tell me what to change, or ask me to save it again."

#: On a resumed run's tool result carrying the owner's answer to a question
#: card (app.gateway.resume.QUESTION_ANSWER_MARKER, the same key).
QUESTION_ANSWER_KEY = "omniharness_question_answer"

#: On the builder's own "what should it do?" question (its tool result) and
#: on the owner's card answer to it: harness-written, the owner's words, so
#: they do not make the turn "content" (app.policy.lineage).
BUILDER_QUESTION_MARKER = "omniharness_builder_question"
OWNER_ANSWER_MARKER = "omniharness_owner_answer"
