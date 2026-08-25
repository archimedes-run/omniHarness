"""A minimal gateway exposing the Tier 3 flow, for the cross-worker test.

NOT a fixture of the flow — it wires the REAL objects: PolicyMiddleware,
PendingStore, confirm.recognise, PolicyAuditLog. What it strips is the agent and
the model, because neither participates in the claim-and-execute path this test
is about.

Run under `uvicorn --workers N`. Each worker imports this module in its own
process, which is the whole point: the pending store, the claim and the audit
log must work across processes that share nothing but the filesystem.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request

from app.gateway.internal_auth import INTERNAL_AUTH_HEADER_NAME, is_valid_internal_auth_token
from app.policy.audit import PolicyAuditLog
from app.policy.config import ConfigLoader
from app.policy.confirm import recognise  # noqa: F401
from app.policy.disclose import DisclosureLedger
from app.policy.middleware import PolicyMiddleware
from app.policy.pending import PendingStore

STATE_DIR = Path(os.environ["POLICY_TEST_STATE_DIR"])
RULES = Path(os.environ["POLICY_TEST_RULES"])

app = FastAPI()

_store = PendingStore(directory=STATE_DIR / "pending")
_audit = PolicyAuditLog(path=STATE_DIR / "audit.jsonl", actor="default")
_middleware = PolicyMiddleware(
    loader=ConfigLoader(path=RULES),
    pending=_store,
    ledger=DisclosureLedger(),
    resolve_targets=lambda name, args: list(args.get("targets", [])),
    audit=_audit,
    actor="default",
)

#: Proof of execution that survives the process. Each worker appends its own
#: file; a count > 1 across all of them means the action ran twice.
EXECUTIONS = STATE_DIR / "executions"


def _request(name: str, args: dict):
    return SimpleNamespace(
        tool_call={"name": name, "args": args, "id": "tc1", "type": "tool_call"},
        tool=SimpleNamespace(name=name),
        state={"messages": []},
        runtime=SimpleNamespace(context={"thread_id": "t1"}),
    )


@app.post("/state")
async def state_a_plan(request: Request):
    """Worker A: classify, refuse, and record a durable pending action."""
    body = await request.json()
    plan = _middleware.wrap_tool_call(
        _request(body["tool"], body.get("args", {})),
        lambda r: (_ for _ in ()).throw(AssertionError("a Tier 3 tool executed without confirmation")),
    )
    return {"pid": os.getpid(), "plan": plan, "pending": [a.id for a in _store.open_actions(datetime.now(UTC))]}


@app.post("/confirm")
async def confirm(request: Request):
    """Whichever worker the kernel picks: the SHARED flow, not a copy of it.

    This endpoint used to inline recognise -> claim -> execute_confirmed. That
    was the only implementation in existence, which is how a test app came to
    hold the sole copy of a production behaviour. It now calls
    `ConfirmationFlow`, the same object the chat route uses, so what this proves
    about cross-worker confirmation is a fact about production and not about
    this file.
    """
    if not is_valid_internal_auth_token(request.headers.get(INTERNAL_AUTH_HEADER_NAME)):
        # Exercises the shared-secret fix: a per-worker token would 401 here
        # whenever the reply lands on a worker other than the one that minted it.
        return {"pid": os.getpid(), "error": "internal auth rejected", "executed": False}

    body = await request.json()
    from langchain_core.messages import HumanMessage

    from app.policy.confirm_flow import EXECUTED, ConfirmationFlow

    flow = ConfirmationFlow(store=_store, middleware=_middleware, now=lambda: datetime.now(UTC))

    def _run(tool_name, args):
        EXECUTIONS.mkdir(parents=True, exist_ok=True)
        (EXECUTIONS / f"{os.getpid()}-{tool_name}-{len(list(EXECUTIONS.iterdir()))}").write_text(f"{tool_name} {args}")
        return "done"

    result = flow.from_message(
        HumanMessage(content=body["reply"]),
        run_tool=_run,
        runtime_context={"thread_id": "t1"},
    )
    return {
        "pid": os.getpid(),
        "executed": result.outcome == EXECUTED,
        "verdict": result.outcome,
        "reason": result.message,
        "claimant": f"worker-{os.getpid()}" if result.outcome == EXECUTED else None,
    }


@app.get("/health")
async def health():
    return {"pid": os.getpid()}
