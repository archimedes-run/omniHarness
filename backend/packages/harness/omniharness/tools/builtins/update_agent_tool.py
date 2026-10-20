"""update_agent tool — let a custom agent persist updates to its own SOUL.md / config.

Bound to the lead agent only when ``runtime.context['agent_name']`` is set
(i.e. inside an existing custom agent's chat). The default agent does not see
this tool, and the bootstrap flow continues to use ``setup_agent`` for the
initial creation handshake.

The tool writes back to ``{base_dir}/users/{user_id}/agents/{agent_name}/{config.yaml,SOUL.md}``
so an agent created by one user is never visible to (or mutable by) another.
Writes go through the versioned store (omniharness.config.config_versions):
each update is a new version, source "proposal", undoable, and both files are
staged before either is replaced, so a partial failure cannot leave config.yaml
updated while SOUL.md still holds stale content.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from omniharness.config import config_versions
from omniharness.config.agents_config import load_agent_config, validate_agent_name
from omniharness.config.app_config import get_app_config
from omniharness.config.paths import get_paths
from omniharness.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


@tool
def update_agent(
    runtime: ToolRuntime,
    soul: str | None = None,
    description: str | None = None,
    skills: list[str] | None = None,
    tool_groups: list[str] | None = None,
    model: str | None = None,
) -> Command:
    """Persist updates to the current custom agent's SOUL.md and config.yaml.

    Use this when the user asks to refine the agent's identity, description,
    skill whitelist, tool-group whitelist, or default model. Only the fields
    you explicitly pass are updated; omitted fields keep their existing values.

    Pass ``soul`` as the FULL replacement SOUL.md content — there is no patch
    semantics, so always start from the current SOUL and apply your edits.

    Pass ``skills=[]`` to disable all skills for this agent. Omit ``skills``
    entirely to keep the existing whitelist.

    Args:
        soul: Optional full replacement SOUL.md content.
        description: Optional new one-line description.
        skills: Optional skill whitelist. ``[]`` = no skills, omit = unchanged.
        tool_groups: Optional tool-group whitelist. ``[]`` = empty, omit = unchanged.
        model: Optional model override (must match a configured model name).

    Returns:
        Command with a ToolMessage describing the result. Changes take effect
        on the next user turn (when the lead agent is rebuilt with the fresh
        SOUL.md and config.yaml).
    """
    tool_call_id = runtime.tool_call_id
    agent_name_raw: str | None = runtime.context.get("agent_name") if runtime.context else None

    def _err(message: str) -> Command:
        return Command(update={"messages": [ToolMessage(content=f"Error: {message}", tool_call_id=tool_call_id)]})

    if soul is None and description is None and skills is None and tool_groups is None and model is None:
        return _err("No fields provided. Pass at least one of: soul, description, skills, tool_groups, model.")

    try:
        agent_name = validate_agent_name(agent_name_raw)
    except ValueError as e:
        return _err(str(e))

    if not agent_name:
        return _err("update_agent is only available inside a custom agent's chat. There is no agent_name in the current runtime context, so there is nothing to update. If you are inside the bootstrap flow, use setup_agent instead.")

    # Resolve the active user so that updates only affect this user's agent.
    # ``get_effective_user_id`` returns DEFAULT_USER_ID when no auth context
    # is set (matching how memory and thread storage behave).
    user_id = get_effective_user_id()

    # Reject an unknown ``model`` *before* touching the filesystem. Otherwise
    # ``_resolve_model_name`` silently falls back to the default at runtime
    # and the user sees confusing repeated warnings on every later turn.
    if model is not None and get_app_config().get_model_config(model) is None:
        return _err(f"Unknown model '{model}'. Pass a model name that exists in config.yaml's models section.")

    paths = get_paths()
    agent_dir = paths.user_agent_dir(user_id, agent_name)
    if not agent_dir.exists() and paths.agent_dir(agent_name).exists():
        return _err(f"Agent '{agent_name}' only exists in the legacy shared layout and is not scoped to a user. Run scripts/migrate_user_isolation.py to move legacy agents into the per-user layout before updating.")

    try:
        existing_cfg = load_agent_config(agent_name, user_id=user_id)
    except FileNotFoundError:
        return _err(f"Agent '{agent_name}' does not exist for the current user. Use setup_agent to create a new agent first.")
    except ValueError as e:
        return _err(f"Agent '{agent_name}' has an unreadable config: {e}")

    if existing_cfg is None:
        return _err(f"Agent '{agent_name}' could not be loaded.")

    updated_fields: list[str] = []

    # Start from the config on record, every key kept (display name, projects,
    # autonomy, anything added later); only what was passed changes. The
    # version is read with it and sent back as base_version, so an edit made
    # by someone else in between (the user in Agent Studio) is never
    # overwritten: the write is refused instead.
    current_snapshot, read_version = config_versions.current_agent_state(user_id, agent_name)
    current = current_snapshot or {}
    config_data: dict[str, Any] = dict(current.get("config") or {})
    # Force the on-disk ``name`` to match the directory we are writing into,
    # even if ``existing_cfg.name`` had drifted (e.g. from manual yaml edits).
    config_data["name"] = agent_name
    config_data["description"] = description if description is not None else existing_cfg.description
    if description is not None and description != existing_cfg.description:
        updated_fields.append("description")
    for key, passed in (("model", model), ("tool_groups", tool_groups), ("skills", skills)):
        existing = getattr(existing_cfg, key)
        value = passed if passed is not None else existing
        if value is not None:
            config_data[key] = value
        if passed is not None and passed != existing:
            updated_fields.append(key)
    if soul is not None:
        updated_fields.append("soul")

    if updated_fields or config_data.get("name") != (current.get("config") or {}).get("name"):
        new_soul = soul if soul is not None else (current.get("soul") or "")
        try:
            # Through the versioned store: the agent changing itself is a
            # proposal it applied, recorded as such and undoable.
            config_versions.write_agent(user_id, agent_name, {"config": config_data, "soul": new_soul}, who=f"agent:{agent_name}", source="proposal", base_version=read_version)
        except config_versions.StaleWriteError as e:
            logger.info("[update_agent] Refused a stale update to agent '%s' (user=%s): %s", agent_name, user_id, e)
            return _err(f"Agent '{agent_name}' was changed by someone else while you were updating it, so nothing was saved ({e}). Read the current setup again and redo the change on top of it.")
        except Exception as e:
            logger.error("[update_agent] Failed to update agent '%s' (user=%s): %s", agent_name, user_id, e, exc_info=True)
            return _err(f"Failed to update agent '{agent_name}': {e}")

    if not updated_fields:
        return Command(update={"messages": [ToolMessage(content=f"No changes applied to agent '{agent_name}'. The provided values matched the existing config.", tool_call_id=tool_call_id)]})

    logger.info("[update_agent] Updated agent '%s' (user=%s) fields: %s", agent_name, user_id, updated_fields)
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=(f"Agent '{agent_name}' updated successfully. Changed: {', '.join(updated_fields)}. The new configuration takes effect on the next user turn."),
                    tool_call_id=tool_call_id,
                )
            ]
        }
    )
