"""THE model boundary for tool names: full name inside, provider-safe alias on the wire.

Model providers accept a tool (function) name only if it matches
``^[a-zA-Z0-9_-]{1,64}$``. Tool names in this process are longer than that
when a source prefixes an already long name: a connector toolkit's tools load
as ``connector-<toolkit>_<UPSTREAM_SLUG>`` (``tool_name_prefix=True``), and
``connector-github_GITHUB_LIST_REPOSITORIES_STARRED_BY_THE_AUTHENTICATED_USER``
is 75 characters. The provider answered every request that offered it, or
carried it in history, with a 400 (``string_above_max_length``).

The FULL name is canonical everywhere in the process: tool registration, the
ToolNode, the policy layer (tiers, private reads, provenance, grants,
confirmations), run history and the UI. Only the request sent to the provider
carries an alias, and the reply is mapped back to full names BEFORE anything
else sees it. So a rule is never checked against an alias, and an alias can
never match some other tool's rule: no alias exists outside this boundary.

How it is installed: ``ToolNameBoundaryMiddleware`` (in the shared middleware
base every agent is built from) swaps the request's model for
:class:`ToolNameBoundaryModel`, which aliases at ``bind_tools`` and at
``invoke``, the last step before the provider, wherever the middleware sits in
the chain. A direct ``bind_tools`` outside an agent wraps its model in
:class:`ToolNameBoundaryModel` too (tests/test_tool_name_boundary.py gates
both).

An alias is deterministic and collision-free: names the provider accepts pass
unchanged; any other name becomes a sanitised prefix, ``_``, and the first hex
digits of the SHA-256 of the full name, at most 64 characters. Within one
request the mapping is a bijection: if an alias would equal another name in
the request (an offered tool's name, or another alias), a longer digest is
used, and if no digest length separates them the request fails closed
(:class:`ToolNameCollisionError`) rather than letting one name stand for two
tools.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections.abc import Callable, Iterable
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import Runnable, RunnableConfig

logger = logging.getLogger(__name__)

#: The provider limit (OpenAI-compatible APIs and Anthropic alike).
MAX_TOOL_NAME_LENGTH = 64
#: What a provider accepts as a tool name.
MODEL_SAFE_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
#: Digest lengths tried in order when an alias would collide.
_DIGEST_LENGTHS = (10, 16, 24, 32, 48)
_UNSAFE_CHARS = re.compile(r"[^a-zA-Z0-9_-]")

#: Content-block types that carry a tool name (Anthropic, Responses API).
_TOOL_BLOCK_TYPES = frozenset({"tool_use", "tool_call", "function_call", "tool_call_chunk"})
#: ``tool_choice`` values that are modes, not tool names.
_TOOL_CHOICE_MODES = frozenset({"auto", "any", "none", "required"})


class ToolNameCollisionError(RuntimeError):
    """Two different tool names would reach the model under one name."""


def is_model_safe(name: str) -> bool:
    return bool(MODEL_SAFE_TOOL_NAME.match(name or ""))


def alias_for(name: str, digest_length: int = _DIGEST_LENGTHS[0]) -> str:
    """The provider-safe name for ``name``: itself when already safe."""
    if is_model_safe(name):
        return name
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:digest_length]
    stem = _UNSAFE_CHARS.sub("_", name)[: MAX_TOOL_NAME_LENGTH - 1 - digest_length] or "tool"
    return f"{stem}_{digest}"


# -- process-wide record of minted aliases (display only) ---------------------
#
# The model's streamed chunks and the raw responses the run journal records
# are seen before the boundary maps the reply back, so they carry the alias.
# They are display surfaces, so they look the alias up here. Nothing that
# DECIDES anything (policy, dispatch) reads this: those see the reply only
# after the boundary rewrote it from the request's own mapping.

_MINTED: dict[str, str | None] = {}
_MINTED_LOCK = threading.Lock()
_MINTED_CAP = 50_000


def _record(alias: str, full: str) -> None:
    with _MINTED_LOCK:
        if len(_MINTED) > _MINTED_CAP:
            _MINTED.clear()
        known = _MINTED.get(alias, full)
        # An alias ever seen for two names is ambiguous: shown as is.
        _MINTED[alias] = full if known == full else None


def display_name(name: str) -> str:
    """The full name for an alias this process minted, else ``name``."""
    with _MINTED_LOCK:
        return _MINTED.get(name) or name


class ToolNameAliases:
    """One request's bijection between full tool names and model names."""

    def __init__(self, names: Iterable[str] = ()) -> None:
        self._to_model: dict[str, str] = {}
        self._to_full: dict[str, str] = {}
        self.add(names)

    def add(self, names: Iterable[str]) -> None:
        """Register names; names already registered keep their alias."""
        new = sorted({n for n in names if isinstance(n, str) and n and n not in self._to_model})
        # Safe names first: they pass unchanged and so claim their spelling.
        for name in new:
            if is_model_safe(name):
                if name in self._to_full:
                    # An alias minted earlier in this request is this very
                    # spelling: two tools, one name.
                    raise ToolNameCollisionError(f"tool name {name!r} equals the model name of {self._to_full[name]!r}")
                self._to_model[name] = name
                self._to_full[name] = name
        for name in new:
            if is_model_safe(name):
                continue
            for length in _DIGEST_LENGTHS:
                alias = alias_for(name, length)
                if alias not in self._to_full:
                    break
            else:
                raise ToolNameCollisionError(f"no collision-free model name for tool {name!r}")
            self._to_model[name] = alias
            self._to_full[alias] = name
            _record(alias, name)

    def to_model(self, name: str) -> str:
        if name not in self._to_model:
            self.add([name])
        return self._to_model[name]

    def to_full(self, name: str) -> str:
        """The full name for a model name of THIS request; anything else unchanged."""
        return self._to_full.get(name, name)

    @property
    def aliased(self) -> dict[str, str]:
        """``{alias: full}`` for the names that needed one."""
        return {a: f for a, f in self._to_full.items() if a != f}


# -- renaming inside messages -------------------------------------------------


def _rename_calls(calls: Any, rename: Callable[[str], str]) -> tuple[Any, bool]:
    if not isinstance(calls, list):
        return calls, False
    out, changed = [], False
    for call in calls:
        if isinstance(call, dict) and isinstance(call.get("name"), str):
            new = rename(call["name"])
            if new != call["name"]:
                call, changed = {**call, "name": new}, True
        out.append(call)
    return out, changed


def _rename_raw_calls(calls: Any, rename: Callable[[str], str]) -> tuple[Any, bool]:
    """``additional_kwargs["tool_calls"]``: OpenAI wire shape."""
    if not isinstance(calls, list):
        return calls, False
    out, changed = [], False
    for call in calls:
        fn = call.get("function") if isinstance(call, dict) else None
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            new = rename(fn["name"])
            if new != fn["name"]:
                call, changed = {**call, "function": {**fn, "name": new}}, True
        out.append(call)
    return out, changed


def _rename_blocks(content: Any, rename: Callable[[str], str]) -> tuple[Any, bool]:
    if not isinstance(content, list):
        return content, False
    out, changed = [], False
    for block in content:
        if isinstance(block, dict) and block.get("type") in _TOOL_BLOCK_TYPES and isinstance(block.get("name"), str):
            new = rename(block["name"])
            if new != block["name"]:
                block, changed = {**block, "name": new}, True
        out.append(block)
    return out, changed


def rename_message(message: Any, rename: Callable[[str], str]) -> Any:
    """``message`` with every tool name passed through ``rename`` (a copy if any changed)."""
    if isinstance(message, ToolMessage):
        if isinstance(message.name, str) and rename(message.name) != message.name:
            return message.model_copy(update={"name": rename(message.name)})
        return message
    if not isinstance(message, AIMessage):
        return message
    update: dict[str, Any] = {}
    for field in ("tool_calls", "invalid_tool_calls", "tool_call_chunks"):
        value, changed = _rename_calls(getattr(message, field, None), rename)
        if changed:
            update[field] = value
    content, changed = _rename_blocks(message.content, rename)
    if changed:
        update["content"] = content
    kwargs = dict(message.additional_kwargs or {})
    raw, raw_changed = _rename_raw_calls(kwargs.get("tool_calls"), rename)
    if raw_changed:
        kwargs["tool_calls"] = raw
    fc = kwargs.get("function_call")
    if isinstance(fc, dict) and isinstance(fc.get("name"), str) and rename(fc["name"]) != fc["name"]:
        kwargs["function_call"], raw_changed = {**fc, "name": rename(fc["name"])}, True
    if raw_changed:
        update["additional_kwargs"] = kwargs
    return message.model_copy(update=update) if update else message


def message_tool_names(message: Any) -> list[str]:
    """Every tool name a message carries."""
    seen: list[str] = []
    rename_message(message, lambda n: seen.append(n) or n)
    return seen


def rename_serialized_message(data: Any, rename: Callable[[str], str]) -> Any:
    """The same renaming on a serialised (``model_dump``) message dict."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    if out.get("type") in ("tool", "ToolMessageChunk"):
        if isinstance(out.get("name"), str):
            out["name"] = rename(out["name"])
        return out
    for field in ("tool_calls", "invalid_tool_calls", "tool_call_chunks"):
        if field in out:
            out[field] = _rename_calls(out[field], rename)[0]
    if "content" in out:
        out["content"], _ = _rename_blocks(out["content"], rename)
    kwargs = out.get("additional_kwargs")
    if isinstance(kwargs, dict) and "tool_calls" in kwargs:
        out["additional_kwargs"] = {**kwargs, "tool_calls": _rename_raw_calls(kwargs["tool_calls"], rename)[0]}
    return out


# -- the boundary --------------------------------------------------------------


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        fn = tool.get("function")
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            return fn["name"]
        name = tool.get("name")
        return name if isinstance(name, str) else None
    name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None


def _renamed_tool(tool: Any, alias: str) -> Any:
    if isinstance(tool, dict):
        fn = tool.get("function")
        if isinstance(fn, dict) and "name" in fn:
            return {**tool, "function": {**fn, "name": alias}}
        return {**tool, "name": alias}
    if hasattr(tool, "model_copy"):
        return tool.model_copy(update={"name": alias})
    raise ToolNameCollisionError(f"cannot offer tool {_tool_name(tool)!r} under a model-safe name")


def _renamed_choice(choice: Any, aliases: ToolNameAliases) -> Any:
    if isinstance(choice, str) and choice not in _TOOL_CHOICE_MODES:
        return aliases.to_model(choice)
    if isinstance(choice, dict):
        fn = choice.get("function")
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            return {**choice, "function": {**fn, "name": aliases.to_model(fn["name"])}}
        if isinstance(choice.get("name"), str):
            return {**choice, "name": aliases.to_model(choice["name"])}
    return choice


class _BoundaryRunnable(Runnable):
    """A bound model whose input is aliased and whose output is restored."""

    def __init__(self, bound: Runnable, aliases: ToolNameAliases) -> None:
        self.bound = bound
        self.aliases = aliases

    def _to_model(self, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        # History may name tools no longer offered (or names from before this
        # boundary existed, up to 88 characters): alias them too.
        self.aliases.add(n for m in value for n in message_tool_names(m))
        return [rename_message(m, self.aliases.to_model) for m in value]

    def _to_full(self, value: Any) -> Any:
        if isinstance(value, BaseMessage):
            return rename_message(value, self.aliases.to_full)
        return value

    def invoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        return self._to_full(self.bound.invoke(self._to_model(input), config, **kwargs))

    async def ainvoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        return self._to_full(await self.bound.ainvoke(self._to_model(input), config, **kwargs))

    def stream(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any):
        for chunk in self.bound.stream(self._to_model(input), config, **kwargs):
            yield self._to_full(chunk)

    async def astream(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any):
        async for chunk in self.bound.astream(self._to_model(input), config, **kwargs):
            yield self._to_full(chunk)


class ToolNameBoundaryModel:
    """A chat model whose tool names reach the provider model-safe.

    Delegates everything to the wrapped model except ``bind_tools`` and
    ``bind``, the two ways the agent factory turns a model into what it
    invokes.
    """

    def __init__(self, model: Any) -> None:
        self._model = model.inner if isinstance(model, ToolNameBoundaryModel) else model

    @property
    def inner(self) -> Any:
        return self._model

    def __getattr__(self, name: str) -> Any:
        return getattr(self._model, name)

    def bind_tools(self, tools: list, *args: Any, **kwargs: Any) -> _BoundaryRunnable:
        aliases = ToolNameAliases(n for n in map(_tool_name, tools) if n)
        offered = []
        for tool in tools:
            name = _tool_name(tool)
            offered.append(_renamed_tool(tool, aliases.to_model(name)) if name and aliases.to_model(name) != name else tool)
        if "tool_choice" in kwargs:
            kwargs["tool_choice"] = _renamed_choice(kwargs["tool_choice"], aliases)
        if aliases.aliased:
            logger.info("tool names offered to the model under an alias: %s", aliases.aliased)
        return _BoundaryRunnable(self._model.bind_tools(offered, *args, **kwargs), aliases)

    def bind(self, **kwargs: Any) -> _BoundaryRunnable:
        return _BoundaryRunnable(self._model.bind(**kwargs), ToolNameAliases())
