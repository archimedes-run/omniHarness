"""When each tool source last WORKED (Feature 006, two-stage integration status).

A connector Composio reports ACTIVE is only reported; one whose tool call came
back without error was observed working. This keeps, per source and per user,
the last observed success and the last observed failure, so the chat bar can
say "Connected" until a call has worked and "Live · last worked <time>" after.
"""

from omniharness.persistence.tool_source_health.model import ToolSourceHealthRow
from omniharness.persistence.tool_source_health.sql import LOCAL_OWNER, SourceHealth, ToolSourceHealthRepository

__all__ = ["LOCAL_OWNER", "SourceHealth", "ToolSourceHealthRepository", "ToolSourceHealthRow"]
