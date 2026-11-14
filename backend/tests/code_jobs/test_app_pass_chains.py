"""Design passes belong to the owner request that started them (Spec 011):
a new owner message is a new update with its own three passes, and the
lead's untagged retry is a pass only inside the turn that asked for it."""

from __future__ import annotations

import re
import uuid

from .test_app_mode import app_result
from .test_app_mode_http import AppFake, build
from .test_app_update_http import UPDATE, approved_today
from .test_code_job_http import SANDBOX, gateway  # noqa: F401 - the fixture

OVERFLOW = app_result({("light", "fresh"): {360: {"overflow_px": 400}}})


def _lead(first_args: dict):
    """Starts one job per owner message with *first_args*, then runs every
    design pass a result asks for (fix_of from the result), then stops."""
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class Lead(BaseChatModel):
        disable_streaming: bool = True

        @property
        def _llm_type(self) -> str:
            return "chain-lead"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
            results = [m for m in messages[last_human:] if isinstance(m, ToolMessage)]
            call = None
            if not results:
                call = {"name": "code_job", "args": first_args, "id": f"c{uuid.uuid4().hex[:8]}"}
            elif m := re.search(r'Run design pass \d of 3 now with fix_of="(\w+)"', str(results[-1].content)):
                call = {"name": "code_job", "args": {"goal": "Design pass: fix these without changing behaviour or sources", "project_dir": "today", "fix_of": m.group(1)}, "id": f"c{uuid.uuid4().hex[:8]}"}
            message = AIMessage(content="", tool_calls=[call]) if call else AIMessage(content="Reported.")
            return ChatResult(generations=[ChatGeneration(message=message)])

    return Lead()


def _ask(gateway, thread_id: str, text: str) -> list:  # noqa: F811
    before = {j.id for j in gateway.client.app.state.code_job_store.for_thread(thread_id)}
    resp = gateway.client.post(f"/api/threads/{thread_id}/runs/wait", json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": text}]}, "context": {"mode": "pro"}})
    assert resp.status_code == 200, resp.text
    jobs = [j for j in gateway.client.app.state.code_job_store.for_thread(thread_id) if j.id not in before]
    return sorted(jobs, key=lambda j: j.created_at)


def _chain(jobs) -> None:
    """One update and its three automatic passes, all failing their checks."""
    update, *passes = jobs
    assert len(passes) == 3, [j.result.get("fix_of") for j in jobs]
    assert update.result.get("fix_of") is None and update.result["app"]["update"] is True
    assert [p.result["design_passes_used"] for p in passes] == [1, 2, 3]
    assert all(p.result["app"]["root"] == update.id for p in passes)


def test_a_new_owner_message_is_a_new_update_with_its_own_passes(gateway, monkeypatch):  # noqa: F811
    thread_id = approved_today(gateway)
    monkeypatch.setattr("omniharness.agents.lead_agent.agent.create_chat_model", lambda **_: _lead(UPDATE))
    SANDBOX["queue"] = [AppFake(build(), probe=OVERFLOW) for _ in range(4)]
    first = _ask(gateway, thread_id, "Change my Today app.")
    _chain(first)
    from app.gateway.code_jobs import app_mode

    assert "All 3 design passes of this app are used: stop and report" in "\n".join(app_mode.report_lines(first[-1], first[-1].result, lambda label, text: [text]))
    SANDBOX["queue"] = [AppFake(build(), probe=OVERFLOW) for _ in range(4)]
    second = _ask(gateway, thread_id, "Update the Today app again: pass time= to the rows.")
    _chain(second)
    assert second[0].result["app"]["root"] == second[0].id != first[0].id
    assert second[0].result["app"]["turn"] != first[0].result["app"]["turn"]


def test_an_untagged_job_after_a_new_owner_message_is_an_update_not_a_pass(gateway, monkeypatch):  # noqa: F811
    thread_id = approved_today(gateway)
    monkeypatch.setattr("omniharness.agents.lead_agent.agent.create_chat_model", lambda **_: _lead(UPDATE))
    SANDBOX["queue"] = [AppFake(build(), probe=OVERFLOW) for _ in range(4)]
    first = _ask(gateway, thread_id, "Change my Today app.")
    assert len(first) == 4
    # The lead leaves out app.update; the owner's message asks for an update.
    untagged = {"goal": "Update the Today app: pass time= to the rows", "project_dir": "today"}
    monkeypatch.setattr("omniharness.agents.lead_agent.agent.create_chat_model", lambda **_: _lead(untagged))
    SANDBOX["queue"] = [AppFake(build())]
    second = _ask(gateway, thread_id, "Update the Today app (app update = today, same sources).")
    job = second[0]
    assert job.result.get("fix_of") is None and job.result["app"]["update"] is True and job.result["app"]["root"] == job.id
    assert job.result["app"].get("design_pass") is False and job.budget_usd == 2.0
