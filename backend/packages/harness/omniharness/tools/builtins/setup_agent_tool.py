import logging

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from omniharness.config import config_versions
from omniharness.config.agents_config import validate_agent_name
from omniharness.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


@tool
def setup_agent(
    soul: str,
    description: str,
    runtime: ToolRuntime,
    skills: list[str] | None = None,
) -> Command:
    """Setup the custom OmniHarness agent.

    Args:
        soul: Full SOUL.md content defining the agent's personality and behavior.
        description: One-line description of what the agent does.
        skills: Optional list of skill names this agent should use. None means use all enabled skills, empty list means no skills.
    """

    agent_name: str | None = runtime.context.get("agent_name") if runtime.context else None

    try:
        agent_name = validate_agent_name(agent_name)
        user_id = get_effective_user_id()
        if agent_name:
            # Custom agents are persisted under the current user's bucket so
            # different users do not see each other's agents.
            config_data: dict = {"name": agent_name}
            if description:
                config_data["description"] = description
            if skills is not None:
                config_data["skills"] = skills
            snapshot = {"config": config_data, "soul": soul}
            target = agent_name
        else:
            # Default agent (no agent_name): its SOUL.md lives at the base dir;
            # the store's "lead_agent" entity keeps its other settings.
            current = config_versions.current_agent_snapshot(user_id, config_versions.LEAD_AGENT) or {}
            snapshot = {"config": current.get("config") or {}, "soul": soul}
            target = config_versions.LEAD_AGENT
        # Through the versioned store; materialising stages both files, so a
        # failure leaves nothing half-written and records no version.
        config_versions.write_agent(user_id, target, snapshot, who=f"user:{user_id}", source="chat")

        logger.info(f"[agent_creator] Created agent '{agent_name}'")
        return Command(
            update={
                "created_agent_name": agent_name,
                "messages": [ToolMessage(content=f"Agent '{agent_name}' created successfully!", tool_call_id=runtime.tool_call_id)],
            }
        )

    except Exception as e:
        logger.error(f"[agent_creator] Failed to create agent '{agent_name}': {e}", exc_info=True)
        return Command(update={"messages": [ToolMessage(content=f"Error: {e}", tool_call_id=runtime.tool_call_id)]})
