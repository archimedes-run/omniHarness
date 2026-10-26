import { readFileSync } from "fs";
import { resolve } from "path";

import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "vitest";

import {
  appendUnique,
  fetchRunMessages,
  historyBeforeLive,
  isMiddlewareStreamed,
  mergeDisplay,
  messagesMovedBySummary,
  moveIntoHistory,
  summarizationUpdate,
  type RunMessageRow,
} from "@/core/threads/summarization";

/**
 * What the chat does when the agent's context is summarized (dogfooding,
 * 2026-10-24), against the stream and journal recorded from the real backend
 * (tests/rendering/fixtures/summarized-research.json).
 */
const FIX = JSON.parse(
  readFileSync(
    resolve(__dirname, "../rendering/fixtures/summarized-research.json"),
    "utf8",
  ),
) as {
  run2_sse: string;
  state1: { values: { messages: Message[] } };
  journal2: Record<string, RunMessageRow[]>;
  state2: { values: { messages: Message[] } };
  leaked_summary_chunks: string[];
};

function events(sse: string): { event: string; data: unknown }[] {
  return sse
    .split("\n\n")
    .map((block) => {
      const lines = block.split("\n");
      const event = lines
        .find((l) => l.startsWith("event:"))
        ?.slice(6)
        .trim();
      const data = lines.find((l) => l.startsWith("data:"))?.slice(5);
      return event && data
        ? { event, data: JSON.parse(data) as unknown }
        : null;
    })
    .filter((e): e is { event: string; data: unknown } => e !== null);
}

const updates = events(FIX.run2_sse)
  .filter((e) => e.event.startsWith("updates"))
  .map((e) => e.data as Record<string, { messages?: Message[] } | null>);

describe("a summarized turn's stream", () => {
  it("finds the summarization update by its summary message, whatever the node is called", () => {
    const found = updates.filter((u) => summarizationUpdate(u) !== null);
    expect(found.length).toBeGreaterThan(1);
    // The recorded node name is the middleware class's, not the base class's.
    expect(Object.keys(found[0]!)).toEqual([
      "OmniHarnessSummarizationMiddleware.before_model",
    ]);
    expect(
      updates.filter(
        (u) => "SummarizationMiddleware.before_model" in (u ?? {}),
      ),
    ).toHaveLength(0);
  });

  it("moves every replaced message into the history, each once, in order", () => {
    // As the chat does: its copy of the live thread is the latest state the
    // stream showed (each "values" event); each summarization moves what it
    // replaced into the history.
    let live: Message[] = FIX.state1.values.messages;
    let history: Message[] = [];
    for (const { event, data } of events(FIX.run2_sse)) {
      if (event.startsWith("values")) {
        live = (data as { messages: Message[] }).messages;
        continue;
      }
      if (!event.startsWith("updates")) continue;
      const summarized = summarizationUpdate(data as Record<string, unknown>);
      if (summarized) {
        history = appendUnique(
          history,
          messagesMovedBySummary(live, summarized),
        );
      }
    }
    const shown = [...history, ...live].filter(
      (m) => !(m.type === "human" && m.name === "summary"),
    );
    const humans = shown
      .filter((m) => m.type === "human")
      .map((m) =>
        Array.isArray(m.content)
          ? (m.content[0] as { text: string }).text
          : m.content,
      );
    expect(humans).toEqual(["now find 3 brunch spots too"]);
    const tools = shown.filter((m) => m.type === "tool");
    // The first turn's last fetch (still in its state), then the second
    // turn's search and three fetches.
    expect(tools.map((m) => m.name)).toEqual([
      "web_fetch",
      "web_search",
      "web_fetch",
      "web_fetch",
      "web_fetch",
    ]);
    const ids = shown.map((m) => m.id);
    expect(new Set(ids).size).toBe(ids.length);
    // The live thread ends as the backend's state does: summary + the last few.
    expect(live[0]?.name).toBe("summary");
  });

  it("tells a middleware's streamed model call from the agent's", () => {
    const [chunk] = events(FIX.leaked_summary_chunks.join("\n\n"));
    const [, metadata] = chunk!.data as [unknown, Record<string, unknown>];
    expect(isMiddlewareStreamed({ streamMetadata: metadata })).toBe(true);
    expect(
      isMiddlewareStreamed({ streamMetadata: { tags: ["seq:step:1"] } }),
    ).toBe(false);
    expect(isMiddlewareStreamed(undefined)).toBe(false);
  });
});

describe("the display history after a reload", () => {
  it("reads a run's journal page by page until its first row", async () => {
    const [, rows] = Object.entries(FIX.journal2).at(-1)!;
    const asked: string[] = [];
    const serve = async (url: string) => {
      asked.push(url);
      const before = new URL(url, "http://x").searchParams.get("before_seq");
      const older =
        before === null ? rows : rows.filter((r) => r.seq < Number(before));
      const data = older.slice(-4);
      return { data, has_more: older.length > data.length };
    };
    let next: number | null = null;
    let messages: Message[] = [];
    do {
      const page = await fetchRunMessages(serve, "/api/run", next);
      messages = [...page.messages, ...messages];
      next = page.next;
    } while (next !== null);
    expect(asked[0]).toBe("/api/run?limit=200");
    expect(asked.length).toBeGreaterThan(1);
    // The person's message is the run's oldest row; the summarizer's own
    // rows are middleware calls and never shown.
    expect(messages[0]?.type).toBe("human");
    expect(JSON.stringify(messages)).not.toContain("SESSION INTENT");
    expect(messages).toHaveLength(
      rows.filter((r) => !r.metadata.caller?.startsWith("middleware:")).length,
    );
  });
});

describe("a reload while a run is still going (D1-g)", () => {
  const msg = (id: string, type: "human" | "ai" = "ai"): Message => ({
    id,
    type,
    content: id,
  });
  const tool = (id: string, call: string): Message => ({
    id,
    type: "tool",
    tool_call_id: call,
    content: id,
  });

  it("shows the running run's journal up to where the live thread begins, each message once", () => {
    // The journal is written as the run goes, so it can be AHEAD of the
    // thread state the chat loaded (a3 journaled, its checkpoint not yet in).
    const history = [
      msg("h2", "human"),
      msg("a1"),
      tool("t1", "c1"),
      msg("a2"),
      tool("t2", "c2"),
      msg("a3"),
    ];
    const live = [msg("summary", "human"), msg("a2"), tool("t2-copy", "c2")];
    const shown = mergeDisplay(history, live, []);
    expect(shown.map((m) => m.id)).toEqual([
      "h2",
      "a1",
      "t1",
      "summary",
      "a2",
      "t2-copy",
    ]);
  });

  it("keeps the whole history when the live thread holds none of it", () => {
    const history = [msg("h1", "human"), msg("a1")];
    expect(historyBeforeLive(history, [msg("x")])).toBe(history);
  });

  it("puts what a later summarization moves after what was shown before the live thread, in order", () => {
    // Reloaded mid-run before this run summarized: the history holds the
    // running run's journal, the live thread still holds the older turns.
    const history = [msg("h2", "human"), msg("a1")];
    const live = [
      msg("h1", "human"),
      msg("f1"),
      msg("h2", "human"),
      msg("a1"),
      msg("a2"),
    ];
    const moved = live.slice(0, 4);
    const next = moveIntoHistory(history, live, moved);
    expect(next.map((m) => m.id)).toEqual(["h1", "f1", "h2", "a1"]);
    // Appending to the whole history put the older turn after the newer one.
    expect(appendUnique(history, moved).map((m) => m.id)).toEqual([
      "h2",
      "a1",
      "h1",
      "f1",
    ]);
  });

  it("is not cut at an earlier turn's tool result that reuses a call id", () => {
    // Recorded: both turns' fetches are "f3"; the live thread keeps the
    // second turn's. The journal's tool rows carry no message id.
    const history = Object.values(FIX.journal2).flatMap((rows) =>
      rows
        .filter((row) => !row.metadata?.caller?.startsWith("middleware:"))
        .map((row) => row.content),
    );
    const shown = mergeDisplay(history, FIX.state2.values.messages, []);
    const texts = JSON.stringify(shown);
    expect(texts).toContain("Run one answer: Vetri Cucina");
    expect(
      shown.filter((m) => m.type === "human" && m.name !== "summary"),
    ).toHaveLength(2);
    const ids = shown.map((m) => m.id).filter(Boolean);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("a summary that keeps a rescued copy of an earlier message (skill rescue)", () => {
  const RESCUED = { additional_kwargs: { omniharness_summary_rescued: true } };
  const h = (id: string) => ({ id, type: "human", content: id }) as Message;
  const a = (id: string, extra = {}) =>
    ({ id, type: "ai", content: id, ...extra }) as Message;
  const t = (call: string, extra = {}) =>
    ({ type: "tool", tool_call_id: call, content: call, ...extra }) as Message;
  const summary = {
    id: "s",
    type: "human",
    name: "summary",
    content: "summary",
  } as Message;
  // a1 loaded a skill (its result c1); the summary keeps a COPY of a1 (same
  // id) and c1 after itself, then the recent tail h4, a4.
  const full = [
    h("h1"),
    a("a1"),
    t("c1"),
    a("a1b"),
    h("h2"),
    a("a2"),
    h("h3"),
    a("a3"),
    h("h4"),
    a("a4"),
  ];
  const live = [summary, a("a1", RESCUED), t("c1", RESCUED), h("h4"), a("a4")];
  const ids = (ms: Message[]) =>
    ms.filter((m) => m.name !== "summary").map((m) => m.id ?? m.content);

  it("after a reload, shows every turn once: the copy does not mark where the live thread begins", () => {
    expect(ids(mergeDisplay(full, live, []))).toEqual(ids(full));
  });

  it("while streaming, moves every replaced message, not only those before the copy's original", () => {
    const update = [
      { type: "remove", id: "__remove_all__" } as Message,
      ...live,
    ];
    const moved = messagesMovedBySummary(full, update);
    expect(ids(moved)).toEqual([
      "h1",
      "a1",
      "c1",
      "a1b",
      "h2",
      "a2",
      "h3",
      "a3",
    ]);
    const history = moveIntoHistory([], full, moved);
    expect(ids(mergeDisplay(history, live, []))).toEqual(ids(full));
  });

  it("an unmarked live message with an old id still marks where the live thread begins", () => {
    expect(
      historyBeforeLive(full, [summary, a("a3"), h("h4")]).map((m) => m.id),
    ).toEqual(["h1", "a1", undefined, "a1b", "h2", "a2", "h3"]);
  });
});
