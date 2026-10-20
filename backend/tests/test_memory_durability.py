"""Memory keeps durable things, not task residue (Phase 2.6).

Top of mind was filling with file paths (/mnt/user-data/outputs/...), tool
steps and one-off searches. The prompt now forbids them, and durability.py
guarantees it: these tests give the updater a model that ignores the prompt,
and check that nothing transient is stored anyway.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from omniharness.agents.memory import storage as storage_module
from omniharness.agents.memory.durability import durable_text, transient_markers
from omniharness.agents.memory.prompt import MEMORY_CLEANUP_PROMPT, MEMORY_UPDATE_PROMPT
from omniharness.agents.memory.storage import FileMemoryStorage, create_empty_memory
from omniharness.agents.memory.updater import MemoryUpdater, get_memory_data

#: What a careless memory model writes after a tool-heavy task.
LEAKY = {
    "user": {
        "workContext": {"summary": "Leads analytics at a retail startup. Saved the report to /mnt/user-data/outputs/retention.md for review.", "shouldUpdate": True},
        "personalContext": {"summary": "Prefers short answers with tables.", "shouldUpdate": True},
        "topOfMind": {
            "summary": "Building a customer retention dashboard. Step 1: ran `pnpm build` in ~/projects/dash. Then call the web_search tool for churn benchmarks. Used read_file( on config.yaml. Planning a board presentation next month.",
            "shouldUpdate": True,
        },
    },
    "history": {"recentMonths": {"summary": "Worked through cohort analysis; ran `python3 cohort.py --weeks 12` repeatedly.", "shouldUpdate": True}},
    "newFacts": [
        {"content": "Prefers tables over prose", "category": "preference", "confidence": 0.95},
        {"content": "Output stored at /mnt/user-data/outputs/retention.md", "category": "context", "confidence": 0.95},
        {"content": "Ran `git push -f` on the dashboard repo", "category": "behavior", "confidence": 0.9},
    ],
}


class _Model:
    def __init__(self, reply: dict) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def invoke(self, prompt, config=None):
        self.prompts.append(prompt)
        return SimpleNamespace(content=json.dumps(self.reply))


@pytest.fixture
def memory_file(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
    store = FileMemoryStorage()
    monkeypatch.setattr(store, "_get_memory_file_path", lambda *a, **k: path)
    monkeypatch.setattr(storage_module, "_storage_instance", store)
    store.save(create_empty_memory())
    return path


def _stored_text(path) -> list[str]:
    data = json.loads(path.read_text())
    texts = [s["summary"] for g in ("user", "history") for s in data[g].values()]
    return texts + [f["content"] for f in data["facts"]]


def test_a_tool_heavy_conversation_stores_no_path_command_or_step(memory_file, monkeypatch) -> None:
    conversation = [
        HumanMessage(content="Build me a retention dashboard and save it."),
        AIMessage(content="", tool_calls=[{"name": "bash", "args": {"command": "cd ~/projects/dash && pnpm build"}, "id": "t1"}]),
        ToolMessage(content="built to /mnt/user-data/outputs/retention.md", tool_call_id="t1"),
        AIMessage(content="Step 2: I'll call web_search for churn benchmarks, then write /mnt/user-data/outputs/retention.md."),
        HumanMessage(content="Great, I prefer tables. This is for my board presentation next month."),
        AIMessage(content="Done. The report is at /mnt/user-data/outputs/retention.md."),
    ]
    updater = MemoryUpdater()
    model = _Model(LEAKY)
    monkeypatch.setattr(updater, "_get_model", lambda: model)

    assert updater.update_memory(conversation, thread_id="t-e2e") is True

    stored = _stored_text(memory_file)
    offending = {t: transient_markers(t) for t in stored if transient_markers(t)}
    assert offending == {}, f"task residue reached memory: {offending}"
    joined = " ".join(stored)
    assert "/mnt/" not in joined and "pnpm" not in joined and "Step 1" not in joined
    # Durable content survives the scrub.
    assert "retention dashboard" in joined and "board presentation" in joined
    assert "Prefers tables over prose" in joined
    # And the model was told the rules in the first place.
    assert "What Memory Is NOT For" in model.prompts[0]


def test_the_prompt_names_what_memory_is_not_for() -> None:
    for phrase in ("File paths", "Commands", "Step-by-step task details", "One-off searches"):
        assert phrase in MEMORY_UPDATE_PROMPT
        assert phrase.lower().split()[0] in MEMORY_CLEANUP_PROMPT.lower()


@pytest.mark.parametrize(
    "sentence",
    [
        "Saved to /mnt/user-data/outputs/report.md.",
        "Repo lives in ~/Documents/GitHub/omniHarness.",
        "Opened C:\\Users\\me\\notes.txt yesterday.",
        "Ran `docker compose up -d` to start it.",
        "$ make daily",
        "Step 3: deploy.",
        "Then call the gmail tool.",
        "Used the web_search tool for prices.",
        "Called read_file( to check.",
    ],
)
def test_transient_sentences_are_recognised(sentence) -> None:
    assert transient_markers(sentence), sentence


@pytest.mark.parametrize(
    "sentence",
    [
        "Works on OmniHarness, an agent platform (https://github.com/archimedes-run/omniHarness).",
        "Prefers TypeScript and/or Python for tooling.",
        "Collaborates with Darcy on scheduling; lives in New York.",
        "Building a retention dashboard for the board.",
    ],
)
def test_durable_sentences_are_kept(sentence) -> None:
    assert transient_markers(sentence) == []
    assert durable_text(sentence) == sentence


# --- editing a summary, and the one-time cleanup, through the routes ----------


@pytest.fixture
def client(memory_file):
    from app.gateway.routers import memory

    app = make_authed_test_app()
    app.include_router(memory.router)
    return TestClient(app)


def _seed(text: str) -> None:
    data = get_memory_data()
    data = json.loads(json.dumps(data))
    data["user"]["topOfMind"] = {"summary": text, "updatedAt": "2026-08-01T00:00:00Z"}
    data["facts"] = [
        {"id": "f1", "content": "Prefers tables", "category": "preference", "confidence": 0.9, "createdAt": "2026-08-01T00:00:00Z", "source": "t"},
        {"id": "f2", "content": "Wrote /mnt/user-data/outputs/a.md", "category": "context", "confidence": 0.9, "createdAt": "2026-08-01T00:00:00Z", "source": "t"},
    ]
    storage_module.get_memory_storage().save(data)


def test_a_summary_section_can_be_corrected(client) -> None:
    resp = client.put("/api/memory/sections/user/workContext", json={"summary": "Founder of OmniHarness."})

    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["workContext"]["summary"] == "Founder of OmniHarness."
    assert resp.json()["user"]["workContext"]["updatedAt"], "a correction is stamped as fresh"
    assert client.put("/api/memory/sections/user/nope", json={"summary": "x"}).status_code == 404


def test_cleanup_previews_without_saving_then_applies_what_was_accepted(client, monkeypatch) -> None:
    _seed("Building a retention dashboard. Saved output to /mnt/user-data/outputs/a.md. Then call the search tool.")
    before = get_memory_data()["user"]["topOfMind"]["summary"]
    model = _Model({"user.topOfMind": "Building a retention dashboard. Wrote it to /mnt/user-data/outputs/a.md."})
    monkeypatch.setattr(MemoryUpdater, "_get_model", lambda self: model)

    preview = client.post("/api/memory/cleanup/preview").json()

    top = next(s for s in preview["sections"] if s["key"] == "topOfMind")
    assert top["before"] == before and top["changed"] is True
    assert top["after"] == "Building a retention dashboard.", "the model's own leak must be scrubbed too"
    assert [f["id"] for f in preview["factsToRemove"]] == ["f2"]
    assert get_memory_data()["user"]["topOfMind"]["summary"] == before, "a preview saved something"

    applied = client.post("/api/memory/cleanup/apply", json={"version": preview["version"], "sections": {"user.topOfMind": top["after"]}, "factsToRemove": ["f2"]})

    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["user"]["topOfMind"]["summary"] == "Building a retention dashboard."
    assert body["user"]["topOfMind"]["updatedAt"] == "2026-08-01T00:00:00Z", "a cleanup must not make stale memory look fresh"
    assert [f["id"] for f in body["facts"]] == ["f1"]


def test_cleanup_is_refused_if_memory_changed_since_the_preview(client, monkeypatch) -> None:
    _seed("Building a dashboard.")
    monkeypatch.setattr(MemoryUpdater, "_get_model", lambda self: _Model({"user.topOfMind": "Building a dashboard."}))
    preview = client.post("/api/memory/cleanup/preview").json()
    client.put("/api/memory/sections/user/personalContext", json={"summary": "Changed meanwhile."})

    resp = client.post("/api/memory/cleanup/apply", json={"version": preview["version"], "sections": {"user.topOfMind": "x"}, "factsToRemove": []})

    assert resp.status_code == 409
    assert get_memory_data()["user"]["topOfMind"]["summary"] == "Building a dashboard."
