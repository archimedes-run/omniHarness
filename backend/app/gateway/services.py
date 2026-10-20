"""Run lifecycle service layer.

Centralizes the business logic for creating runs, formatting SSE
frames, and consuming stream bridge events.  Router modules
(``thread_runs``, ``runs``) are thin HTTP handlers that delegate here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import HTTPException, Request
from langchain_core.messages import HumanMessage

from app.gateway.deps import get_current_user, get_run_context, get_run_manager, get_stream_bridge
from app.gateway.utils import sanitize_log_param
from omniharness.runtime import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    ConflictError,
    DisconnectMode,
    RunContext,
    RunManager,
    RunRecord,
    RunStatus,
    StreamBridge,
    UnsupportedStrategyError,
    run_agent,
    serialize_channel_values,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SSE formatting
# ---------------------------------------------------------------------------


def format_sse(event: str, data: Any, *, event_id: str | None = None) -> str:
    """Format a single SSE frame.

    Field order: ``event:`` -> ``data:`` -> ``id:`` (optional) -> blank line.
    This matches the LangGraph Platform wire format consumed by the
    ``useStream`` React hook and the Python ``langgraph-sdk`` SSE decoder.
    """
    payload = json.dumps(data, default=str, ensure_ascii=False)
    parts = [f"event: {event}", f"data: {payload}"]
    if event_id:
        parts.append(f"id: {event_id}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Input / config helpers
# ---------------------------------------------------------------------------


def normalize_stream_modes(raw: list[str] | str | None) -> list[str]:
    """Normalize the stream_mode parameter to a list.

    Default matches what ``useStream`` expects: values + messages-tuple.
    """
    if raw is None:
        return ["values"]
    if isinstance(raw, str):
        return [raw]
    return raw if raw else ["values"]


def normalize_input(raw_input: dict[str, Any] | None, *, user_turn: bool = True, keep_id: Callable[[Any], bool] | None = None) -> dict[str, Any]:
    """Convert LangGraph Platform input format to LangChain state dict.

    The person's own human message(s) are tagged as the user's turn
    (lineage.USER_TURN_MARKER), here and nowhere else. Every message is
    rebuilt from role and content only, so a marker a client put in
    ``additional_kwargs`` never survives, and a message with any other role is
    never the user's turn.
    """
    from app.policy.lineage import user_turn as tagged

    if raw_input is None:
        return {}
    if not isinstance(raw_input, Mapping):
        raise ValueError("input must be an object")
    unknown = sorted(k for k in raw_input if k != "messages")
    if unknown:
        # Only messages are input. Any other key would be written straight into
        # graph state, past every check here.
        logger.info("normalize_input: dropped input keys %s", unknown)
    messages = raw_input.get("messages")
    if messages is None:
        return {}
    if not isinstance(messages, list):
        # A single object used to pass through untouched, keeping any client
        # kwargs, a forged user-turn marker included.
        raise ValueError("input.messages must be a list")
    raw_input = {"messages": messages}
    if messages:
        converted = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", msg.get("type", "user"))
                content = msg.get("content", "")
                if role in ("user", "human"):
                    # Only the trigger engine's signed, thread-bound, single-use
                    # turn id is kept (`keep_id`, set by start_run for the
                    # engine's own requests; run history, Feature 006). Any
                    # other id is dropped: add_messages replaces by id, so
                    # keeping it would let a caller rewrite an earlier message.
                    msg_id = msg.get("id") if keep_id is not None and keep_id(msg.get("id")) else None
                    kw = {"id": msg_id} if msg_id else {}
                    converted.append(tagged(content, **kw) if user_turn else HumanMessage(content=content, **kw))
                else:
                    # TODO: handle other message types (system, ai, tool)
                    converted.append(HumanMessage(content=content))
            else:
                # Not from JSON: never trusted as a user turn.
                converted.append(HumanMessage(content=getattr(msg, "content", str(msg))))
        return {**raw_input, "messages": converted}
    return raw_input


_DEFAULT_ASSISTANT_ID = "lead_agent"


# Whitelist of run-context keys that the langgraph-compat layer forwards from
# ``body.context`` into the run config. ``config["context"]`` exists in
# LangGraph >=0.6, but these values must be written to both ``configurable``
# (for legacy ``_get_runtime_config`` consumers) and ``context`` because
# LangGraph >=1.1.9 no longer makes ``ToolRuntime.context`` fall back to
# ``configurable`` for consumers like ``setup_agent``.
_CONTEXT_CONFIGURABLE_KEYS: frozenset[str] = frozenset(
    {
        "model_name",
        "mode",
        "thinking_enabled",
        "reasoning_effort",
        "is_plan_mode",
        "subagent_enabled",
        "max_concurrent_subagents",
        "agent_name",
        "is_bootstrap",
        # Feature 002 turn provenance. These are read at TOOL DISPATCH, by a
        # middleware's wrap_tool_call, whose ToolCallRequest exposes only
        # {tool_call, tool, state, runtime} — no run config. The only container
        # that reaches it is ``config["context"]``, via _build_runtime_context.
        "turn_provenance",
        "trigger_rule_id",
        # Feature 006: which firing a scheduled run is, for the standing-grant
        # cap (app/policy/grants.GrantRunCounts).
        "trigger_firing_id",
    }
)


#: Run-context keys ONLY THE SERVER SETS (security baseline, item b).
#:
#: Whatever a client sends under these names — in ``body.context``,
#: ``config.configurable``, ``config.context``, ``config.metadata`` or
#: ``body.metadata`` — is dropped by :func:`apply_server_owned_context`, which
#: then writes the server's own value (assigned, never ``setdefault``):
#:
#: - ``user_id``: the authenticated caller (AuthMiddleware's decision);
#: - ``selected_sources``: this thread's stored tool selection;
#: - ``agent_name``: the agent the caller selected (``assistant_id``, or the
#:   chat UI's ``context.agent_name``), normalised and validated. It only ever
#:   resolves inside the caller's own agents directory, because ``user_id`` is
#:   server-set;
#: - ``turn_provenance`` / ``trigger_rule_id``: only when the caller presents
#:   a single-use grant the trigger engine issued for that exact request
#:   (internal_auth.is_trigger_engine_request);
#: - ``called_agent``: never from a request (set inside delegation only);
#: - ``excluded_skills``: this thread's stored exclusions;
#: - ``channel``: the IM channel, from the channel manager's header with the
#:   internal token only (internal_auth.channel_of).
SERVER_OWNED_RUN_KEYS: frozenset[str] = frozenset(
    {
        "user_id",
        "selected_sources",
        "agent_name",
        "turn_provenance",
        "trigger_rule_id",
        "called_agent",
        "excluded_skills",
        "channel",
    }
)

#: Keys a client may pass through ``body.context``: the whitelist minus every
#: server-owned key.
_CLIENT_CONTEXT_KEYS: frozenset[str] = _CONTEXT_CONFIGURABLE_KEYS - SERVER_OWNED_RUN_KEYS

#: Metadata keys a client may never set on a run or a thread.
_SERVER_OWNED_METADATA_KEYS: frozenset[str] = SERVER_OWNED_RUN_KEYS | {"owner_id", "invited_agent", "delegation_chain", "sandbox_id", "run_id"}

#: ALLOWLISTS (security baseline, review round): what a client may put in each
#: run-config container. Everything else is dropped before the server writes
#: its own keys, so a key the runtime later reads as identity or authority
#: (invited_agent, delegation_chain, sandbox_id, ...) can never arrive from a
#: request, including keys nobody has thought of yet.
_CLIENT_CONFIGURABLE_KEYS: frozenset[str] = _CLIENT_CONTEXT_KEYS | {"thread_id", "checkpoint_ns", "checkpoint_id"}
#: Run metadata a client may set (descriptive only). Everything else, e.g.
#: callbacks, __pregel_*, continue_action, is dropped.
_CLIENT_METADATA_KEYS: frozenset[str] = frozenset({"title", "source"})
_CLIENT_TOP_LEVEL_CONFIG_KEYS: frozenset[str] = frozenset({"recursion_limit", "tags", "run_name", "max_concurrency", "metadata", "configurable", "context"})


def _client_requested_agent(body: Any) -> str | None:
    """Which agent the caller asked for, before validation.

    ``assistant_id`` is the LangGraph field for it; the chat UI sends
    ``assistant_id="lead_agent"`` with ``context.agent_name`` instead, and the
    IM channels did the same. Both are a CHOICE the caller is entitled to make;
    the value that reaches the run is the server's normalised one.
    """
    assistant_id = getattr(body, "assistant_id", None)
    if assistant_id and assistant_id != _DEFAULT_ASSISTANT_ID:
        return assistant_id
    # The chat UI's selector. Only here: a name placed in config.configurable,
    # config.context or metadata is stripped, never read as a choice.
    body_context = getattr(body, "context", None)
    value = body_context.get("agent_name") if isinstance(body_context, Mapping) else None
    return value if isinstance(value, str) and value.strip() else None


def _normalise_agent_name(raw: str) -> str:
    normalized = raw.strip().lower().replace("_", "-")
    if not normalized or not re.fullmatch(r"[a-z0-9-]+", normalized):
        raise ValueError(f"Invalid agent name {raw!r}: must contain only letters, digits, and hyphens after normalization.")
    return normalized


def _client_provenance(body: Any) -> tuple[str | None, str | None]:
    """The (turn_provenance, trigger_rule_id) a request claims, wherever it put them."""
    cfg = getattr(body, "config", None) or {}
    containers = [cfg.get("configurable"), cfg.get("context"), cfg.get("metadata"), getattr(body, "metadata", None), getattr(body, "context", None)]
    provenance = rule = None
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        provenance = provenance or container.get("turn_provenance")
        rule = rule or container.get("trigger_rule_id")
    return (provenance if isinstance(provenance, str) else None, rule if isinstance(rule, str) else None)


def apply_server_owned_context(
    config: dict[str, Any],
    metadata: dict[str, Any],
    *,
    user_id: str | None,
    selected_sources: list[str] | None,
    agent_name: str | None,
    synthetic_rule_id: str | None,
) -> None:
    """Drop every client-supplied server-owned key, then write the server's.

    ``config`` is the run config and ``metadata`` the run's metadata (stored on
    the run record, where ``injector.is_synthetic`` reads provenance). Both are
    edited in place. ``synthetic_rule_id`` is not None only for a request the
    trigger engine made (the caller checks the credential).
    """
    from app.policy.provenance import PROVENANCE_KEY, RULE_KEY, SYNTHETIC

    for key in [k for k in config if k not in _CLIENT_TOP_LEVEL_CONFIG_KEYS]:
        config.pop(key)
    for name, allowed in (("configurable", _CLIENT_CONFIGURABLE_KEYS), ("context", _CLIENT_CONTEXT_KEYS)):
        container = config.get(name)
        if isinstance(container, dict):
            for key in [k for k in container if k not in allowed]:
                container.pop(key)
        elif container is not None:
            config.pop(name)
    if config.get("metadata") is not None and not isinstance(config.get("metadata"), dict):
        config.pop("metadata")
    for container in (config.get("metadata"), metadata):
        if isinstance(container, dict):
            for key in [k for k in container if k not in _CLIENT_METADATA_KEYS]:
                container.pop(key)

    context = config.get("context")
    if not isinstance(context, dict):
        context = {}
        config["context"] = context
    configurable = config.get("configurable") if isinstance(config.get("configurable"), dict) else None

    if user_id:
        context["user_id"] = user_id
    if selected_sources is not None:
        context["selected_sources"] = list(selected_sources)
    if agent_name:
        context["agent_name"] = agent_name
        if configurable is not None:
            configurable["agent_name"] = agent_name
    if synthetic_rule_id is not None:
        marks = {PROVENANCE_KEY: SYNTHETIC, RULE_KEY: synthetic_rule_id}
        context.update(marks)
        if configurable is not None:
            configurable.update(marks)
        metadata.update(marks)


def merge_run_context_overrides(config: dict[str, Any], context: Mapping[str, Any] | None) -> None:
    """Merge whitelisted keys from ``body.context`` into both ``config['configurable']``
    and ``config['context']`` so they are visible to legacy configurable readers and
    to LangGraph ``ToolRuntime.context`` consumers (e.g. the ``setup_agent`` tool —
    see issue #2677)."""
    if not context:
        return
    configurable = config.setdefault("configurable", {})
    runtime_context = config.setdefault("context", {})
    for key in _CLIENT_CONTEXT_KEYS:
        if key in context:
            if isinstance(configurable, dict):
                configurable.setdefault(key, context[key])
            if isinstance(runtime_context, dict):
                runtime_context.setdefault(key, context[key])


def _mirror_runtime_visible_keys(config: dict[str, Any]) -> None:
    """Copy whitelisted keys from ``configurable`` into ``context``.

    ``ToolRuntime.context`` is built from ``config["context"]`` alone, so a key
    that only ever lands in ``configurable`` is invisible to anything reading
    runtime context — including a middleware's ``wrap_tool_call``, whose
    ``ToolCallRequest`` carries no run config at all.

    LangGraph used to bridge this itself: ``ToolRuntime.context`` fell back to
    ``configurable``. That fallback was removed in >=1.1.9 (see the note above
    ``_CONTEXT_CONFIGURABLE_KEYS``), and nothing failed at the time because
    nothing was reading provenance from tool context yet. This restores the
    bridge explicitly, for a named set of keys rather than for everything.

    Callers must NOT work around this by sending both containers: when a request
    carries ``context`` and ``configurable`` together, :func:`build_run_config`
    prefers ``context`` and drops ``configurable`` wholesale — taking
    ``thread_id`` with it. Send ``configurable``; this mirrors.
    """
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return
    context = config.get("context")
    if not isinstance(context, dict):
        if not any(k in configurable for k in _CONTEXT_CONFIGURABLE_KEYS):
            return
        context = config.setdefault("context", {})
    if not isinstance(context, dict):
        return
    for key in _CONTEXT_CONFIGURABLE_KEYS:
        if key in configurable:
            context.setdefault(key, configurable[key])


#: Runtime-context keys only the server may set (see start_run).
SERVER_OWNED_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "tool_surface",
        "invited_origin",
        "invited_origin_source",
        "invited_via",
        "invited_agent",
        "delegation_chain",
        "called_agent",
        "delegation_key",
        "resume_action",
        "stopped_at",
    }
)


def strip_server_owned_context(config: dict[str, Any]) -> None:
    for container in (config.get("configurable"), config.get("context")):
        if isinstance(container, dict):
            for key in SERVER_OWNED_CONTEXT_KEYS:
                container.pop(key, None)


async def _call_in_mentioned_member(request: Request, thread_id: str, graph_input: dict, config: dict[str, Any]) -> None:
    from app.gateway.routers.thread_participants import stored_participants
    from omniharness.agents.called_agents import CALLED_AGENT_KEY, mentioned_member

    messages = graph_input.get("messages") if isinstance(graph_input, dict) else None
    if not messages:
        return
    last = messages[-1]
    if not isinstance(last, HumanMessage):
        return
    content = last.content
    text = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    if "@" not in text:
        return
    try:
        thread_store = getattr(request.app.state, "thread_store", None)
        user_id = await get_current_user(request)
        members = await stored_participants(thread_store, thread_id, user_id) if thread_store is not None else []
    except Exception:
        logger.warning("Failed to read the members of %s; nobody is called in", sanitize_log_param(thread_id))
        return
    called = mentioned_member(text, members)
    if called:
        ctx_dict = config.setdefault("context", {})
        if isinstance(ctx_dict, dict):
            ctx_dict[CALLED_AGENT_KEY] = called


#: The run body's context key the card's "Continue <agent>" sends: the id of
#: the confirmed action whose agent should carry on. Only an id; everything
#: the run gets from it is read from the server's own record.
CONTINUE_ACTION_KEY = "continue_action"


def _continue_refused(reason: str) -> HTTPException:
    return HTTPException(status_code=409, detail=f"That agent cannot be continued: {reason}")


async def _continue_confirmed_agent(request: Request, thread_id: str, body: Any, config: dict[str, Any]) -> None:
    """ "Continue <agent>" on a confirmed card: re-enter the agent that stopped.

    The body names an action id and nothing else. The server reads the action
    and checks it: confirmed and run, in THIS thread, proposed by an invited
    agent inside a delegation it recorded. Then the turn is handed to that
    agent (the call_agent path), which re-enters its own delegation with the
    confirmed result as observed context (called_agents._resume).
    """
    from omniharness.agents.called_agents import CALLED_AGENT_KEY, RESUME_ACTION_KEY

    raw = getattr(body, "context", None)
    action_id = raw.get(CONTINUE_ACTION_KEY) if isinstance(raw, Mapping) else None
    for container in (config.get("configurable"), config.get("context")):
        if isinstance(container, dict):
            container.pop(CONTINUE_ACTION_KEY, None)
    if not action_id:
        return
    if not isinstance(action_id, str):
        raise _continue_refused("the action id is not text")

    from app.gateway.ownership import require_access
    from app.policy.models import Outcome
    from app.policy.registration import build
    from omniharness.config import get_app_config

    middleware = build(get_app_config())
    action = middleware.pending.get(action_id) if middleware is not None else None
    if action is None:
        raise _continue_refused("no such confirmed action")
    # OWNERSHIP first, before anything about the action is said: another
    # account's action id is "not found", exactly as on the card's route.
    await require_access(request, action.owner_id, what="Confirmation", ident=action_id)
    if action.thread_id != thread_id:
        raise _continue_refused("that action belongs to another chat")
    if action.outcome != Outcome.EXECUTED:
        raise _continue_refused("that action has not run")
    if not action.delegation_key or action.requester == "lead_agent":
        raise _continue_refused("it was not proposed by an agent that stopped in a delegation")
    if action.surface.get("called_agent"):
        from app.gateway.routers.thread_participants import stored_participants

        thread_store = getattr(request.app.state, "thread_store", None)
        members = await stored_participants(thread_store, thread_id, await get_current_user(request)) if thread_store is not None else []
        if action.requester not in members:
            raise _continue_refused(f"{action.requester} is no longer in this chat")
    ctx_dict = config.setdefault("context", {})
    if not isinstance(ctx_dict, dict):
        return
    # ONE AT A TIME, ONE-SHOT ON SUCCESS: a replay would hand the agent "the
    # user confirmed, continue" again. Held from here; spent only when the
    # agent re-enters successfully (called_agents listener -> finish_continue);
    # released if the run is refused, fails or crashes (review of PR #58).
    if not middleware.pending.take_continue(action.id):
        raise _continue_refused("it was already continued for this confirmation, or is being continued now")
    ctx_dict[CALLED_AGENT_KEY] = action.requester
    ctx_dict[RESUME_ACTION_KEY] = {
        "id": action.id,
        "tool_name": action.tool_name,
        "agent": action.requester,
        "delegation_key": action.delegation_key,
        "surface": dict(action.surface),
        "origin": action.origin,
        "origin_source": action.origin_source,
        "origin_via": action.origin_via,
        "delegation_chain": list(action.delegation_chain),
        "result_excerpt": action.result_excerpt,
        "arguments": dict(action.arguments),
    }


def _release_continue_if_held(config: dict[str, Any]) -> None:
    """The run carrying a Continue was refused before it started: the
    Continue did not happen, so it can be pressed again."""
    from omniharness.agents.called_agents import RESUME_ACTION_KEY

    resume = (config.get("context") or {}).get(RESUME_ACTION_KEY) if isinstance(config.get("context"), dict) else None
    if not isinstance(resume, dict) or not resume.get("id"):
        return
    from app.policy.registration import build
    from omniharness.config import get_app_config

    middleware = build(get_app_config())
    if middleware is not None:
        middleware.pending.release_continue(str(resume["id"]))


def resolve_agent_factory(assistant_id: str | None):
    """Resolve the agent factory callable from config.

    Custom agents are implemented as ``lead_agent`` + an ``agent_name``
    injected into ``configurable`` or ``context`` — see
    :func:`build_run_config`.  All ``assistant_id`` values therefore map to the
    same factory; the routing happens inside ``make_lead_agent`` when it reads
    ``cfg["agent_name"]``.
    """
    from omniharness.agents.lead_agent.agent import make_lead_agent

    return make_lead_agent


def build_run_config(
    thread_id: str,
    request_config: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    *,
    assistant_id: str | None = None,
) -> dict[str, Any]:
    """Build a RunnableConfig dict for the agent.

    When *assistant_id* refers to a custom agent (anything other than
    ``"lead_agent"`` / ``None``), the name is forwarded as ``agent_name`` in
    whichever runtime options container is active: ``context`` for
    LangGraph >= 0.6.0 requests, otherwise ``configurable``.
    ``make_lead_agent`` reads this key to load the matching
    ``agents/<name>/SOUL.md`` and per-agent config — without it the agent
    silently runs as the default lead agent.

    This mirrors the channel manager's ``_resolve_run_params`` logic so that
    the LangGraph Platform-compatible HTTP API and the IM channel path behave
    identically.
    """
    config: dict[str, Any] = {"recursion_limit": 100}
    if request_config:
        # LangGraph >= 0.6.0 introduced ``context`` as the preferred way to
        # pass thread-level data and rejects requests that include both
        # ``configurable`` and ``context``.  If the caller already sends
        # ``context``, honour it and skip our own ``configurable`` dict.
        if "context" in request_config:
            if "configurable" in request_config:
                logger.warning(
                    "build_run_config: client sent both 'context' and 'configurable'; preferring 'context' (LangGraph >= 0.6.0). thread_id=%s, caller_configurable keys=%s",
                    thread_id,
                    list(request_config.get("configurable", {}).keys()),
                )
            context_value = request_config["context"]
            if context_value is None:
                context = {}
            elif isinstance(context_value, Mapping):
                context = dict(context_value)
            else:
                raise ValueError("request config 'context' must be a mapping or null.")
            config["context"] = context
        else:
            configurable = {"thread_id": thread_id}
            configurable.update(request_config.get("configurable", {}))
            config["configurable"] = configurable
        for k, v in request_config.items():
            if k not in ("configurable", "context"):
                config[k] = v
    else:
        config["configurable"] = {"thread_id": thread_id}

    # Inject custom agent name when the caller specified a non-default assistant.
    # Honour an explicit agent_name in the active runtime options container.
    if assistant_id and assistant_id != _DEFAULT_ASSISTANT_ID:
        normalized = assistant_id.strip().lower().replace("_", "-")
        if not normalized or not re.fullmatch(r"[a-z0-9-]+", normalized):
            raise ValueError(f"Invalid assistant_id {assistant_id!r}: must contain only letters, digits, and hyphens after normalization.")
        if "configurable" in config:
            target = config["configurable"]
        elif "context" in config:
            target = config["context"]
        else:
            target = config.setdefault("configurable", {})
        if target is not None and "agent_name" not in target:
            target["agent_name"] = normalized
    if metadata:
        config.setdefault("metadata", {}).update(metadata)
    _mirror_runtime_visible_keys(config)
    return config


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


async def launch_agent_run_detached(
    *,
    bridge: StreamBridge,
    run_mgr: RunManager,
    run_ctx: RunContext,
    thread_id: str,
    graph_input: dict,
    run_config: dict,
    assistant_id: str | None = None,
    user_id: str | None = None,
    metadata: dict | None = None,
    multitask_strategy: str = "reject",
    on_disconnect: DisconnectMode = DisconnectMode.continue_,
    stream_modes: list[str] | str | None = None,
    stream_subgraphs: bool = False,
    interrupt_before: Any = None,
    interrupt_after: Any = None,
) -> RunRecord:
    """Core run-launch: create a RunRecord and start the background agent task.

    This is the single point where ``asyncio.create_task(run_agent(...))`` is
    called.  Both ``start_run()`` (HTTP path) and ``execute_workflow_run()``
    (workflow executor path) call this function — there is no second launch path.

    Callers are responsible for HTTP-specific concerns (error → HTTP mapping,
    reading user auth from cookies).

    Raises:
        ConflictError: when multitask_strategy="reject" and thread has an active run.
        UnsupportedStrategyError: when the strategy is not implemented.
    """
    # Upsert thread metadata so the thread appears in /threads/search.
    if run_ctx.thread_store is not None:
        try:
            existing = await run_ctx.thread_store.get(thread_id)
            if existing is None:
                await run_ctx.thread_store.create(
                    thread_id,
                    assistant_id=assistant_id,
                    user_id=user_id,
                    metadata=metadata,
                )
            else:
                await run_ctx.thread_store.update_status(thread_id, "running")
        except Exception:
            logger.warning("Failed to upsert thread_meta for %s (non-fatal)", sanitize_log_param(thread_id))

    record = await run_mgr.create_or_reject(
        thread_id,
        assistant_id,
        on_disconnect=on_disconnect,
        metadata=metadata or {},
        kwargs={"input": graph_input, "config": run_config},
        multitask_strategy=multitask_strategy,
    )

    agent_factory = resolve_agent_factory(assistant_id)
    resolved_modes = normalize_stream_modes(stream_modes)

    task = asyncio.create_task(
        run_agent(
            bridge,
            run_mgr,
            record,
            ctx=run_ctx,
            agent_factory=agent_factory,
            graph_input=graph_input,
            config=run_config,
            stream_modes=resolved_modes,
            stream_subgraphs=stream_subgraphs,
            interrupt_before=interrupt_before,
            interrupt_after=interrupt_after,
        )
    )
    run_mgr.attach_task(record, task)
    return record


async def start_run(
    body: Any,
    thread_id: str,
    request: Request,
) -> RunRecord:
    """Create a RunRecord and launch the background agent task.

    Parameters
    ----------
    body : RunCreateRequest
        The validated request body (typed as Any to avoid circular import
        with the router module that defines the Pydantic model).
    thread_id : str
        Target thread.
    request : Request
        FastAPI request — used to retrieve singletons from ``app.state``.
    """
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    run_ctx = get_run_context(request)

    disconnect = DisconnectMode.cancel if body.on_disconnect == "cancel" else DisconnectMode.continue_

    # Ownership (item c): every path that starts a run on a thread checks it,
    # including the stateless /api/runs routes, which name the thread in the
    # body rather than the path and so never met the route decorator.
    from app.gateway.internal_auth import is_trigger_engine_request
    from app.gateway.ownership import require_thread_access

    await require_thread_access(request, thread_id)

    # The agent the caller chose, normalised; the run receives the server's value.
    requested_agent = _client_requested_agent(body)
    try:
        agent_name = _normalise_agent_name(requested_agent) if requested_agent else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # A channel message is the user's own turn only when the channel's explicit
    # allowlist vouched for the sender; otherwise it is relayed content.
    from app.gateway.internal_auth import channel_header_present, channel_of, channel_sender_is_owner, trigger_grant_presented  # noqa: F401

    # Who is speaking? A person's own session: the user. The internal
    # principal (channels, the trigger engine, anything holding the token) is
    # the user ONLY for a channel message whose sender the channel's allowlist
    # vouched for, proven by a single-use channel-owner grant. A bare
    # internal-token call is never the user's turn.
    from app.gateway.ownership import is_internal

    caller = getattr(request.state, "user", None)
    if is_internal(caller):
        relayed = not await channel_sender_is_owner(request)
    else:
        relayed = channel_header_present(request)

    # Scheduled-run provenance, decided BEFORE the input is read: only a grant
    # the trigger engine issued for exactly this request marks a turn synthetic.
    # A claim WITH a grant that fails (expired, replayed, mismatched) is refused
    # outright; it must never fall back to an ordinary, user-tagged turn.
    from app.policy.provenance import SYNTHETIC

    synthetic_rule_id: str | None = None
    claimed, rule_id = _client_provenance(body)
    if claimed == SYNTHETIC and trigger_grant_presented(request):
        if not await is_trigger_engine_request(request):
            raise HTTPException(status_code=403, detail="scheduled-run grant refused (expired, already used, or not for this request)")
        synthetic_rule_id = rule_id or ""

    # A scheduled turn's "human" message is a rule's prompt, never the person.
    # The engine's own turn id (run history, Feature 006) is kept only on the
    # engine's granted request, for this thread, once across every worker
    # (the run history's database records it). No history: no id is kept.
    from app.gateway.internal_auth import accept_turn_id

    from_engine = synthetic_rule_id is not None
    history = getattr(request.app.state, "run_history", None)
    consume = history.consume_turn_id if history is not None else (lambda _id: False)
    try:
        graph_input = normalize_input(
            body.input,
            user_turn=not relayed and synthetic_rule_id is None,
            keep_id=lambda v: accept_turn_id(v, thread_id=thread_id, from_trigger_engine=from_engine, consume=consume),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        config = build_run_config(thread_id, body.config, body.metadata, assistant_id=body.assistant_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Merge OmniHarness-specific context overrides into both ``configurable`` and ``context``.
    # The ``context`` field is a custom extension for the langgraph-compat layer
    # that carries agent configuration (model_name, thinking_enabled, etc.).
    # Only client-settable keys are forwarded; server-owned ones never are.
    merge_run_context_overrides(config, getattr(body, "context", None))

    # The authenticated user, as AuthMiddleware decided (cookie or internal).
    user_id = await get_current_user(request)

    # Per-conversation tools: this thread's stored selection (namespaced source
    # ids, pinned enforced by the repo). A thread with no stored selection gets
    # pinned defaults inside the repo. If it cannot be read the key is absent
    # (the agent's default surface), never the client's value.
    selected_sources: list[str] | None = None
    try:
        selection_repo = getattr(request.app.state, "thread_tool_selection_repo", None)
        if selection_repo is not None:
            selected_sources = list(await selection_repo.get_sources(thread_id=thread_id))
    except Exception:
        logger.warning("Failed to load thread tool selection for %s (non-fatal)", sanitize_log_param(thread_id))

    # Scheduled-run provenance: only the trigger engine's own credential may
    # mark a turn synthetic. Anyone else's claim is dropped.

    run_metadata = dict(body.metadata or {})
    apply_server_owned_context(
        config,
        run_metadata,
        user_id=user_id,
        selected_sources=selected_sources,
        agent_name=agent_name,
        synthetic_rule_id=synthetic_rule_id,
    )
    channel = channel_of(request)
    if channel:
        config["context"]["channel"] = channel
    # The thread is the one this request was authorised for, never a value from
    # the body. A request carrying only config.context used to leave no
    # configurable at all, and the run died with KeyError 'thread_id'.
    config_configurable = config.setdefault("configurable", {})
    config_configurable["thread_id"] = thread_id
    config_configurable.setdefault("checkpoint_ns", "")
    # SERVER-OWNED RUN CONTEXT. Who invited an agent, its delegation chain and
    # inherited origin, and the tool surface a confirmation will rebuild are
    # written by the server (the subagent executor, the policy layer), never
    # taken from a client: a run body's `config.context` is honoured wholesale
    # by build_run_config, so these are dropped from it here (plan.md §2.0).
    strip_server_owned_context(config)

    # Feature 006: "@agent" in the USER's own turn calls a member of the chat
    # in. Read from this request's input only (Article III): a mention inside a
    # tool result or an agent's reply is never in it.
    await _call_in_mentioned_member(request, thread_id, graph_input, config)

    # "Continue <agent>" on a confirmed card: the agent that stopped re-enters
    # its own delegation (after the mention: an explicit Continue wins).
    await _continue_confirmed_agent(request, thread_id, body, config)

    # Feature 006: skills removed from this conversation (the chat bar's ×).
    # Always the server's stored value (the client's was dropped above).
    try:
        exclusion_repo = getattr(request.app.state, "thread_skill_exclusion_repo", None)
        if exclusion_repo is not None:
            excluded_skills = await exclusion_repo.get_excluded(thread_id=thread_id, user_id=user_id)
            ctx_dict = config.setdefault("context", {})
            if excluded_skills and isinstance(ctx_dict, dict):
                ctx_dict["excluded_skills"] = excluded_skills
    except Exception:
        logger.warning("Failed to load thread skill exclusion for %s (non-fatal)", sanitize_log_param(thread_id))

    _mirror_runtime_visible_keys(config)

    try:
        record = await launch_agent_run_detached(
            bridge=bridge,
            run_mgr=run_mgr,
            run_ctx=run_ctx,
            thread_id=thread_id,
            graph_input=graph_input,
            run_config=config,
            assistant_id=body.assistant_id,
            user_id=user_id,
            metadata=run_metadata,
            multitask_strategy=body.multitask_strategy,
            on_disconnect=disconnect,
            stream_modes=body.stream_mode,
            stream_subgraphs=body.stream_subgraphs,
            interrupt_before=body.interrupt_before,
            interrupt_after=body.interrupt_after,
        )
    except ConflictError as exc:
        _release_continue_if_held(config)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UnsupportedStrategyError as exc:
        _release_continue_if_held(config)
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    # Title sync is handled by worker.py's finally block which reads the
    # title from the checkpoint and calls thread_store.update_display_name
    # after the run completes.

    return record


async def sse_consumer(
    bridge: StreamBridge,
    record: RunRecord,
    request: Request,
    run_mgr: RunManager,
):
    """Async generator that yields SSE frames from the bridge.

    The ``finally`` block implements ``on_disconnect`` semantics:
    - ``cancel``: abort the background task on client disconnect.
    - ``continue``: let the task run; events are discarded.
    """
    last_event_id = request.headers.get("Last-Event-ID")
    try:
        async for entry in bridge.subscribe(record.run_id, last_event_id=last_event_id):
            if await request.is_disconnected():
                break

            if entry is HEARTBEAT_SENTINEL:
                yield ": heartbeat\n\n"
                continue

            if entry is END_SENTINEL:
                yield format_sse("end", None, event_id=entry.id or None)
                return

            yield format_sse(entry.event, entry.data, event_id=entry.id or None)

    finally:
        if record.status in (RunStatus.pending, RunStatus.running):
            if record.on_disconnect == DisconnectMode.cancel:
                await run_mgr.cancel(record.run_id)


#: How a run that did not succeed is reported by the wait routes. Non-2xx, so a
#: caller checking only the status code is not told a failed run succeeded.
_UNSUCCESSFUL_RUN_STATUS_CODES: dict[str, int] = {
    "error": 500,
    "timeout": 504,
    "interrupted": 409,
}


async def wait_result(record: RunRecord, thread_id: str, request: Request) -> dict:
    """Block until the run finishes; return its final state, or raise.

    The body of both `runs/wait` routes. Each used to return the thread's
    checkpoint whenever one existed, without looking at the run — so a run that
    died before starting answered `200 {}`, indistinguishable from "the run
    produced no messages" (ROADMAP-FOLLOWUPS, "A run that errors returns HTTP
    200"). A run that did not succeed now raises with its status and error.
    """
    from app.gateway.deps import get_checkpointer

    if record.task is not None:
        try:
            await record.task
        except asyncio.CancelledError:
            pass

    status = getattr(record.status, "value", record.status)
    if status in _UNSUCCESSFUL_RUN_STATUS_CODES:
        raise HTTPException(
            status_code=_UNSUCCESSFUL_RUN_STATUS_CODES[status],
            detail={"run_id": record.run_id, "status": status, "error": record.error or ""},
        )

    checkpointer = get_checkpointer(request)
    config = {"configurable": {"thread_id": thread_id}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
        if checkpoint_tuple is not None:
            checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
            channel_values = checkpoint.get("channel_values", {})
            return serialize_channel_values(channel_values)
    except Exception:
        logger.exception("Failed to fetch final state for run %s", record.run_id)

    return {"status": status, "error": record.error}
