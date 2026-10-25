"""A long research chat after summarization (dogfooding, 2026-10-24).

Three things went wrong once a long research turn outgrew the context and the
summarization middleware folded the conversation into a summary:

1. The summary ("## SESSION INTENT / SUMMARY / ARTIFACTS / NEXT STEPS") showed
   in the chat as an assistant message. It is the model's context only. The
   summarizer's chat-model call ran inside a graph node, and the "messages"
   stream mode forwards every such call to the client.
2. The person's own message disappeared. The run journal (the chat's display
   history, `/api/threads/{id}/runs/{run_id}/messages`) recorded the
   summarizer's PROMPT as the run's human input when the summarizer was the
   run's first model call, so the history the chat reloads from had no
   message from the person for that run.
3. Links reached the model defanged (hxxps://a[.]example) from the ledger
   tools' result, and the model copied them into its answer.

Through the production composition: `create_app()` with its lifespan, real
runs through the streaming route the chat uses, the run worker,
`make_lead_agent` with the production summarization middleware in its place,
the real ledger tool and policy layer. Only the chat models are scripted.
"""

from __future__ import annotations

import json
import re

import test_web_research as research
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from test_web_research import gateway  # noqa: F401  (the shared production fixture)

#: What the summarizer saw (its prompt) and wrote, per call.
SUMMARIZER_SAW: list[str] = []
SUMMARIES: list[str] = []

_ANY_URL = re.compile(r"\b(?:https?|hxxps?)://\S+|\bwww(?:\.|\[\.\])\S+", re.I)
VETRI = "https://vetricucina.example/landing/"
ZAHAV = "www.zahavrestaurant.example"


class _Summarizer(GenericFakeChatModel):
    """Writes its summary FROM ITS INPUT, as a real summarizer does: every link
    it was shown is carried into the summary, in the form it was shown."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        prompt = "\n".join(str(m.content) for m in messages)
        SUMMARIZER_SAW.append(prompt)
        links = sorted(set(_ANY_URL.findall(prompt)))
        summary = "## SESSION INTENT\nFind date-night restaurants.\n\n## SUMMARY\nSources: " + " ".join(links) + "\n\n## ARTIFACTS\nNone\n\n## NEXT STEPS\nAnswer."
        SUMMARIES.append(summary)
        self.messages = iter([AIMessage(content=summary)])
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _summarize_early(monkeypatch, *, trigger: int = 5) -> None:
    """The production middleware class, triggering after a few messages (live:
    ~15k tokens, which a research turn of a handful of searches passes). The
    model is tagged exactly as the production factory tags it."""
    from omniharness.agents.middlewares.summarization_middleware import OmniHarnessSummarizationMiddleware

    SUMMARIZER_SAW.clear()
    SUMMARIES.clear()

    def build(**_):
        model = _Summarizer(messages=iter([])).with_config(tags=["middleware:summarize"])
        return OmniHarnessSummarizationMiddleware(model=model, trigger=("messages", trigger), keep=("messages", 2), token_counter=len)

    monkeypatch.setattr("omniharness.agents.lead_agent.agent._create_summarization_middleware", build)


def _with_ledger(monkeypatch) -> None:
    """The real ledger tool beside the stand-in web tools."""
    from omniharness.config import get_app_config
    from omniharness.tools.tools import get_available_tools as real_tools

    [ledger_apply] = [t for t in real_tools(app_config=get_app_config(), include_mcp=False) if t.name == "ledger_apply"]
    monkeypatch.setattr("omniharness.tools.get_available_tools", lambda **_: [*research.LEAD_TOOLS, ledger_apply])


def _stream(gw, thread_id: str, text: str, script: list[AIMessage]) -> list[tuple[str, object]]:
    """One turn through the route and stream modes the chat uses
    (frontend core/threads/hooks.ts): every SSE event, parsed."""
    research.LEAD_SCRIPT[:] = [*script, *[AIMessage(content="(done)")] * 4]
    body = {
        "assistant_id": "lead_agent",
        "input": {"messages": [{"type": "human", "content": [{"type": "text", "text": text}]}]},
        "stream_mode": ["values", "updates", "messages-tuple", "custom"],
        "stream_subgraphs": True,
        "context": {},
    }
    with gw.client.stream("POST", f"/api/threads/{thread_id}/runs/stream", json=body) as resp:
        assert resp.status_code == 200
        raw = "".join(resp.iter_text())
    events, name = [], None
    for line in raw.splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:") and name:
            events.append((name, json.loads(line[5:])))
    return events


def _streamed_messages(events) -> list[tuple[dict, dict]]:
    return [(data[0], data[1]) for name, data in events if name.startswith("messages") and isinstance(data, list) and len(data) == 2]


def _history(gw, thread_id: str) -> list[dict]:
    """The chat's display history, as the frontend reads it (core/threads/
    hooks.ts useThreadHistory): every run, every page, oldest first, minus
    middleware callers."""
    rows: list[dict] = []
    runs = gw.client.get(f"/api/threads/{thread_id}/runs").json()
    for run in sorted(runs, key=lambda r: r["created_at"]):
        page, before = [], None
        while True:
            query = "limit=200" + (f"&before_seq={before}" if before is not None else "")
            got = gw.client.get(f"/api/threads/{thread_id}/runs/{run['run_id']}/messages?{query}").json()
            page = got["data"] + page
            if not got["has_more"]:
                break
            before = got["data"][0]["seq"]
        rows += page
    return [r for r in rows if not str(r["metadata"].get("caller") or "").startswith("middleware:")]


def _human_texts(rows: list[dict]) -> list[str]:
    out = []
    for row in rows:
        content = row["content"]
        if isinstance(content, dict) and content.get("type") == "human":
            body = content.get("content")
            out.append(" ".join(b.get("text", "") for b in body if isinstance(b, dict)) if isinstance(body, list) else str(body))
    return out


def _research(final: str = "Here are your restaurants: https://food1.example/philly") -> list[AIMessage]:
    """A research turn's scripted steps, NEW objects each time: a chat model
    stamps its run id on the message it returns, so a reused AIMessage would
    come back from the next run with the previous run's id."""
    return [
        research._step(research._call("web_search", {"query": "date night restaurants philly"}, "s1")),
        research._step(research._call("web_fetch", {"url": "https://food1.example/philly"}, "f1")),
        research._step(research._call("web_fetch", {"url": "https://food2.example/philly"}, "f2")),
        research._step(research._call("web_fetch", {"url": "https://food3.example/philly"}, "f3")),
        AIMessage(content=final),
    ]


# -- 1. the summary is the model's context, never chat content ------------------


def test_the_summary_never_streams_into_the_chat_and_still_reaches_the_model(gateway, monkeypatch):  # noqa: F811
    _summarize_early(monkeypatch)
    thread_id = research._thread(gateway)
    events = _stream(gateway, thread_id, "find 5 great date-night restaurants in Philly with links", _research())
    assert SUMMARIES, "the turn was never summarized; this test proves nothing"

    streamed = _streamed_messages(events)
    leaked = [(chunk.get("type"), str(chunk.get("content"))[:60], meta.get("tags")) for chunk, meta in streamed if chunk.get("type") != "human" and "SESSION INTENT" in str(chunk.get("content"))]
    assert leaked == [], f"the summarizer's reply streamed into the chat as an assistant message: {leaked}"
    assert not [meta for _chunk, meta in streamed if "middleware:summarize" in (meta.get("tags") or [])], "a summarizer chunk reached the chat stream"
    # The summary that IS in the stream and the state is the context message,
    # named "summary" (the chat hides it: core/messages/utils.ts).
    summaries = [chunk for chunk, _meta in streamed if chunk.get("type") == "human" and "SESSION INTENT" in str(chunk.get("content"))]
    assert summaries and all(chunk.get("name") == "summary" for chunk in summaries), summaries
    state = research._messages(gateway, thread_id)
    assert [m["name"] for m in state if "SESSION INTENT" in str(m["content"])] == ["summary"], state
    # ...and the model still reads it.
    assert any(name == "summary" and "SESSION INTENT" in content for saw in research.LEAD_SAW for _k, name, content in saw)


# -- 2. the person's own messages survive summarization in the chat history -----


def test_the_display_history_keeps_every_message_from_the_person(gateway, monkeypatch):  # noqa: F811
    _summarize_early(monkeypatch)
    thread_id = research._thread(gateway)
    _stream(gateway, thread_id, "find 5 great date-night restaurants in Philly with links", _research())
    # The thread is now long, so the next run's FIRST model call is the
    # summarizer's (before the lead answers at all).
    calls = len(SUMMARIZER_SAW)
    _stream(gateway, thread_id, "now find 3 brunch spots too", _research())
    assert len(SUMMARIZER_SAW) > calls, "the second turn was never summarized; this test proves nothing"

    state = research._messages(gateway, thread_id)
    assert "find 5 great date-night restaurants" not in json.dumps(state), "the first message is still in the model's context; this test proves nothing"
    history = _history(gateway, thread_id)
    assert _human_texts(history) == ["find 5 great date-night restaurants in Philly with links", "now find 3 brunch spots too"]
    # The summarizer's reply is journaled as a middleware call, so the
    # reloaded chat never shows it either.
    assert "SESSION INTENT" not in json.dumps(history), "the summary is in the chat's display history"
    runs = gateway.client.get(f"/api/threads/{thread_id}/runs").json()
    for run in runs:
        rows = gateway.client.get(f"/api/threads/{thread_id}/runs/{run['run_id']}/messages?limit=200").json()["data"]
        inputs = [r for r in rows if r["event_type"] == "llm.human.input"]
        assert len(inputs) == 1 and inputs[0]["metadata"]["caller"] == "lead_agent", inputs
        assert "Messages to summarize" not in json.dumps(inputs), "the summarizer's prompt was recorded as the person's turn"


# -- 3. the model reads real links ----------------------------------------------


def test_a_research_turn_shows_the_model_and_the_summary_real_links(gateway, monkeypatch):  # noqa: F811
    _summarize_early(monkeypatch, trigger=7)
    _with_ledger(monkeypatch)
    assert gateway.client.post("/api/ledger/projects", json={"name": "Dinner"}).status_code == 201
    thread_id = research._thread(gateway)
    save = research._step(
        research._call(
            "ledger_apply",
            {"changes": [{"op": "create_task", "project": "Dinner", "title": f"Book Vetri {VETRI}"}, {"op": "create_task", "project": "Dinner", "title": f"Call Zahav {ZAHAV}"}]},
            "l1",
        )
    )
    # Two turns: the ledger write counts as a private read, which would make
    # the same turn's lookups cards (private_reads.py); a new turn is clean.
    _stream(gateway, thread_id, f"save Vetri ({VETRI}) and Zahav ({ZAHAV}) to Dinner", [save, AIMessage(content="Saved both.")])
    _stream(gateway, thread_id, "now find more date-night places with links", _research())
    assert research._cards(gateway) == [], "a lookup asked for confirmation; this test proves nothing"
    assert SUMMARIES, "the turn was never summarized; this test proves nothing"

    seen = [content for saw in research.LEAD_SAW for _k, _n, content in saw]
    [ledger_result] = {content for saw in research.LEAD_SAW for kind, name, content in saw if kind == "tool" and name == "ledger_apply"}
    assert VETRI in ledger_result and ZAHAV in ledger_result, ledger_result
    search = [content for saw in research.LEAD_SAW for kind, name, content in saw if kind == "tool" and name == "web_search"]
    assert search and all("https://food1.example/philly" in s for s in search), search
    for text in [*seen, *SUMMARIZER_SAW, *SUMMARIES]:
        assert "hxxp" not in text and "[.]" not in text, f"a model was shown a defanged link: {text[:300]}"
    # The summary carries the links the model was shown, real.
    final = SUMMARIES[-1]
    assert VETRI in final and ZAHAV in final and "https://food1.example/philly" in final, final
    state = research._messages(gateway, thread_id)
    [summary] = [m for m in state if m.get("name") == "summary"]
    assert VETRI in summary["content"] and "[.]" not in summary["content"]
