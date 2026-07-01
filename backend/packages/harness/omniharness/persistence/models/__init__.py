"""ORM model registration entry point.

Importing this module ensures all ORM models are registered with
``Base.metadata`` so Alembic autogenerate detects every table.

The actual ORM classes have moved to entity-specific subpackages:
- ``omniharness.persistence.thread_meta``
- ``omniharness.persistence.run``
- ``omniharness.persistence.feedback``
- ``omniharness.persistence.user``

``RunEventRow`` remains in ``omniharness.persistence.models.run_event`` because
its storage implementation lives in ``omniharness.runtime.events.store.db`` and
there is no matching entity directory.
"""

from omniharness.persistence.composio_connections.model import ComposioConnectionRow
from omniharness.persistence.feedback.model import FeedbackRow
from omniharness.persistence.mcp_secrets.model import McpSecretRow
from omniharness.persistence.mcp_server.model import McpServerRow
from omniharness.persistence.models.run_event import RunEventRow
from omniharness.persistence.run.model import RunRow
from omniharness.persistence.thread_meta.model import ThreadMetaRow
from omniharness.persistence.thread_tool_selection.model import ThreadToolSelectionRow
from omniharness.persistence.user.model import UserRow
from omniharness.persistence.workflow_artifact_links.model import WorkflowArtifactLinkRow
from omniharness.persistence.workflow_runs.model import WorkflowRunRow
from omniharness.persistence.workflow_step_runs.model import WorkflowStepRunRow
from omniharness.persistence.workflow_versions.model import WorkflowVersionRow
from omniharness.persistence.workflows.model import WorkflowRow

__all__ = [
    "ComposioConnectionRow",
    "FeedbackRow",
    "McpSecretRow",
    "McpServerRow",
    "RunEventRow",
    "RunRow",
    "ThreadMetaRow",
    "ThreadToolSelectionRow",
    "UserRow",
    "WorkflowArtifactLinkRow",
    "WorkflowRow",
    "WorkflowRunRow",
    "WorkflowStepRunRow",
    "WorkflowVersionRow",
]
