import type { Message } from "@langchain/langgraph-sdk";

/**
 * What the chat shows when the agent's context is summarized.
 *
 * Once a long turn outgrows the model's context, the backend's summarization
 * middleware replaces the thread's checkpointed messages with ONE summary
 * message (a human message named "summary": model context, never shown) plus
 * the few most recent messages. The model needs only that; the person still
 * needs to see everything they said and were shown. So:
 *
 * - while streaming, the messages the summary replaced move from the live
 *   thread into the chat's display history (`messagesMovedBySummary`), found
 *   from the summarization update itself (`summarizationUpdate`), whatever
 *   the middleware node is called;
 * - after a reload, the display history is read back from the run journal,
 *   every page of every run (`fetchRunMessages`), while the thread state stays
 *   summarized.
 */

/** A node update, as the "updates" stream mode sends it. */
type NodeUpdate = { messages?: Message[] } | null | undefined;

function isSummary(message: Message): boolean {
  return message.type === "human" && message.name === "summary";
}

/**
 * The messages of the update that summarized the context, or null when this
 * update did not. Found by its content, not by the node name: the node is
 * named after the middleware class
 * ("OmniHarnessSummarizationMiddleware.before_model"), and matching the base
 * class's name ("SummarizationMiddleware.before_model") silently never fired.
 * A summarization REPLACES the messages (a remove-all, then a summary); an
 * update that merely carries an earlier summary along (a middleware returning
 * the whole list) is not one.
 */
export function summarizationUpdate(
  data: Record<string, unknown> | null | undefined,
): Message[] | null {
  for (const update of Object.values(data ?? {})) {
    const messages = (update as NodeUpdate)?.messages;
    if (
      Array.isArray(messages) &&
      messages.some((m) => m.type === "remove" && m.id === "__remove_all__") &&
      messages.some(isSummary)
    ) {
      return messages;
    }
  }
  return null;
}

/**
 * The messages the summary replaced, in order: everything shown before the
 * first message the summary keeps, minus summary messages themselves.
 * `update` is the summarization update ([remove-all, summary, ...kept]).
 */
export function messagesMovedBySummary(
  current: Message[],
  update: Message[],
): Message[] {
  const kept = update.filter((m) => m.type !== "remove" && !isSummary(m));
  const firstKept = kept[0]?.id;
  const moved: Message[] = [];
  for (const message of current) {
    if (firstKept !== undefined && message.id === firstKept) {
      break;
    }
    if (!isSummary(message)) {
      moved.push(message);
    }
  }
  return moved;
}

function keyOf(message: Message): string | undefined {
  if (message.type === "tool" && "tool_call_id" in message) {
    return `tool:${message.tool_call_id}`;
  }
  return message.id ? `id:${message.id}` : undefined;
}

/**
 * `history` with `more` appended, skipping any message already in it (by id,
 * or a tool result by its call id). The live thread can hold messages the
 * history already loaded from the journal; moving them again showed them
 * twice.
 */
export function appendUnique(history: Message[], more: Message[]): Message[] {
  const seen = new Set(history.map(keyOf).filter(Boolean));
  const added: Message[] = [];
  for (const message of more) {
    const key = keyOf(message);
    if (key && seen.has(key)) {
      continue;
    }
    if (key) {
      seen.add(key);
    }
    added.push(message);
  }
  return added.length > 0 ? [...history, ...added] : history;
}

/**
 * The display history up to where the live thread begins: everything before
 * the first history message (a person's or the agent's, by id) the live
 * thread also holds. From there on the
 * live thread is shown. A run's journal is written as the run goes, so after
 * a reload mid-run it can be AHEAD of the thread state the chat loaded (a
 * reply journaled before its checkpoint reached the chat); keeping only a
 * suffix-overlap trim showed those messages twice, and out of order.
 */
export function historyBeforeLive(
  history: Message[],
  live: Message[],
): Message[] {
  // By message id only. A journaled tool result carries no id, and tool call
  // ids are not unique across runs (a scripted or provider-assigned "f3" in
  // two turns), so matching them cut the history at an earlier turn's result.
  const liveIds = new Set(live.map((message) => message.id).filter(Boolean));
  const first = history.findIndex(
    (message) =>
      message.type !== "tool" && !!message.id && liveIds.has(message.id),
  );
  return first === -1 ? history : history.slice(0, first);
}

/** What the chat shows: the history before the live thread, the live thread, then what is being sent. */
export function mergeDisplay(
  history: Message[],
  live: Message[],
  optimistic: Message[],
): Message[] {
  return [...historyBeforeLive(history, live), ...live, ...optimistic];
}

/**
 * The display history after a summarization moved `moved` out of the live
 * thread `live`: what was shown before the live thread, then the moved
 * messages, in order. Appending them to the whole history put a reloaded
 * run's older messages after its newer ones once the history held the
 * running run's journal.
 */
export function moveIntoHistory(
  history: Message[],
  live: Message[],
  moved: Message[],
): Message[] {
  if (moved.length === 0) {
    return history;
  }
  return appendUnique(historyBeforeLive(history, live), moved);
}

/** One journal row, as `/api/threads/{id}/runs/{run_id}/messages` returns it. */
export interface RunMessageRow {
  seq: number;
  content: Message;
  metadata: { caller?: string };
}

/** The largest page the journal route serves. */
export const RUN_MESSAGES_PAGE = 200;

/**
 * One page of a run's journal, oldest first, with what to ask for next.
 * `before` is the page cursor (a seq); `next` is the cursor for the page
 * before this one, or null when this page starts the run. The route returns
 * the newest page first, so a long run (a research turn with dozens of
 * searches) has several: reading only the first lost the person's message,
 * which is the run's oldest row.
 */
export async function fetchRunMessages(
  fetchJson: (url: string) => Promise<{
    data: RunMessageRow[];
    has_more: boolean;
  }>,
  url: string,
  before: number | null,
): Promise<{ messages: Message[]; next: number | null }> {
  const query = new URLSearchParams({ limit: String(RUN_MESSAGES_PAGE) });
  if (before !== null) {
    query.set("before_seq", String(before));
  }
  const page = await fetchJson(`${url}?${query.toString()}`);
  const rows = page.data ?? [];
  const messages = rows
    .filter((row) => !row.metadata?.caller?.startsWith("middleware:"))
    .map((row) => row.content);
  const oldest = rows[0]?.seq;
  return {
    messages,
    next: page.has_more && typeof oldest === "number" ? oldest : null,
  };
}

/**
 * True for a message the server streamed from a middleware's own model call
 * (the summarizer's reply, the title), told by the stream's metadata: its
 * `middleware:*` tag. The backend keeps these calls out of the stream
 * (the summarizer is tagged "nostream"); this is the chat's own guard.
 */
export function isMiddlewareStreamed(
  metadata: { streamMetadata?: Record<string, unknown> } | null | undefined,
): boolean {
  const tags = metadata?.streamMetadata?.tags;
  return (
    Array.isArray(tags) &&
    tags.some((tag) => typeof tag === "string" && tag.startsWith("middleware:"))
  );
}
