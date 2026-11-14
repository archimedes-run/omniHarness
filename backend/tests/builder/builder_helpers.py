"""Helpers for the chat builder tests (tests/builder/conftest.py builds the gateway)."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage

FS_READ = "filesystem_read_file"
GMAIL_FETCH = "connector-gmail_GMAIL_FETCH_EMAILS"
GMAIL_DRAFT = "connector-gmail_GMAIL_CREATE_EMAIL_DRAFT"


# -- helpers the tests share ---------------------------------------------------


def call(name: str, args: dict, ident: str) -> dict:
    return {"name": name, "args": args, "id": ident}


def script(gw, *steps) -> None:
    """The lead's next replies: each a list of tool calls, or a final text."""
    gw.lead_script[:] = [AIMessage(content="", tool_calls=step) if isinstance(step, list) else AIMessage(content=step) for step in steps]


def new_thread(gw) -> str:
    resp = gw.client.post("/api/threads", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()["thread_id"]


def say(gw, thread_id: str, text: str, *, agent: str = "lead_agent", context: dict | None = None) -> dict:
    # A scripted builder_draft quotes the owner's message it answers, as the
    # model is told to (owner_request), unless the test sets one itself.
    for message in gw.lead_script:
        for tool_call in getattr(message, "tool_calls", None) or []:
            if tool_call.get("name") == "builder_draft" and "owner_request" not in tool_call.get("args", {}):
                tool_call["args"]["owner_request"] = text
    body: dict = {"assistant_id": agent, "input": {"messages": [{"role": "user", "content": text}]}}
    if context:
        body["context"] = context
    resp = gw.client.post(f"/api/threads/{thread_id}/runs/wait", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def offered(bound: list[list[str]]) -> set[str]:
    assert bound, "no model was bound to tools: the run did not happen"
    return set(bound[-1])


def cards(gw, tool: str | None = None) -> list[dict]:
    actions = gw.client.get("/api/confirmations").json()["actions"]
    return [a for a in actions if tool is None or a["tool_name"] == tool]


def make_agent(gw, name: str, **fields) -> dict:
    resp = gw.client.post("/api/agents", json={"name": name, "soul": f"You are {name}.", "skills": [], **fields})
    assert resp.status_code == 201, resp.text
    return resp.json()


def agent_state(gw, name: str):
    from omniharness.config import config_versions

    return config_versions.current_agent_state(gw.user_id, name)


def agent_history(gw, name: str):
    from omniharness.config import config_versions

    return config_versions.agent_history(gw.user_id, name)


def history_records(gw, name: str) -> list[dict]:
    """The agent's history file, read back as written."""
    from omniharness.config import config_versions

    path = config_versions._agent_paths(gw.user_id, name)[0]
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def press(gw, card: dict) -> dict:
    """The card's Confirm button, as the owner presses it, then wait for the
    lead's resume (spec 009 FR-058) to finish, so the chat is free again. The
    resumed lead answers with a plain reply."""
    import time

    gw.lead_script[:] = [AIMessage(content="Ok.")]
    body = gw.client.post(f"/api/confirmations/{card['id']}/confirm", json={}).json()
    run_id = body.get("resume_run_id") or (body.get("detail") or {}).get("resume_run_id")
    if run_id and card.get("thread_id"):
        deadline = time.time() + 30
        while time.time() < deadline:
            status = gw.client.get(f"/api/threads/{card['thread_id']}/runs/{run_id}").json().get("status")
            if status not in ("pending", "running"):
                break
            time.sleep(0.05)
    return body
