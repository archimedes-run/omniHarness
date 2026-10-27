"""Coding jobs (spec 009, Slice 1): the harness-side port.

The harness layer (the `code_job` tool) only imports from here; the gateway
implements the controller (app.gateway.code_jobs), mirroring the preview
controller's boundary.
"""

from .controller import (
    RULES_PATH,
    CodeJobBrief,
    CodeJobController,
    CodeJobOutcome,
    get_code_job_controller,
    reset_code_job_controller,
    rules_text,
    set_code_job_controller,
)

__all__ = [
    "RULES_PATH",
    "CodeJobBrief",
    "CodeJobController",
    "CodeJobOutcome",
    "get_code_job_controller",
    "reset_code_job_controller",
    "rules_text",
    "set_code_job_controller",
]
