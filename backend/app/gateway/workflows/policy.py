"""Approval-policy decision-point for workflow runs (Phase 1 Slice 6)."""


def requires_approval(workflow: dict) -> bool:
    """Return True iff a run on this workflow requires explicit user confirmation.

    v0: approval_required policy → True; all others → False.
    Phase 6 will upgrade the satisfaction mechanism without changing this check.
    """
    return workflow.get("approval_policy") == "approval_required"
