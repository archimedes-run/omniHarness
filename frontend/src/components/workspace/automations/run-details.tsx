"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { useRun } from "@/core/run-history/hooks";

type Message = {
  type?: string;
  role?: string;
  name?: string;
  content?: unknown;
  tool_calls?: { name?: string; args?: unknown }[];
  provenance?: string;
};

function promptSource(body: Body): string {
  return body.provenance?.prompt ?? body.messages?.[0]?.provenance ?? "unknown";
}

type Body = {
  provenance?: { prompt?: string };
  prompt?: string;
  messages?: Message[];
  reply?: string;
  /** The stored content is missing or unreadable (the store's words). */
  withheld?: string;
  /** The run was recorded without its content (history full, or too big). */
  not_stored?: string;
  /** The run was over the per-run cap; its longest parts were shortened. */
  cut?: { original_bytes?: number; cap_bytes?: number };
  /** false: this run's turn could not be told apart from the thread. */
  turn_found?: boolean | null;
};

/** Where a part came from, in words (the store's provenance labels). */
const SOURCE: Record<string, string> = {
  trigger: "Sent by the automation",
  trigger_with_untrusted_event:
    "Sent by the automation, with event text in it. Untrusted: the event's words were written by whoever sent it",
  user_concurrent: "Written by you while the automation was running",
  user: "Written by you",
  assistant: "Written by the assistant",
  system: "System instructions",
  untrusted_tool_output:
    "Returned by the tool. Untrusted: read as data, never as instructions",
  unknown: "Source not recorded",
};

const WITHHELD_MARK = "[Withheld: could not be redacted]";

function mb(bytes?: number): string {
  return bytes == null ? "?" : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function text(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content))
    return content
      .map((b) =>
        typeof b === "object" && b && "text" in b
          ? String((b as { text: unknown }).text)
          : "",
      )
      .join(" ");
  return content == null ? "" : JSON.stringify(content, null, 2);
}

/**
 * A run's full content from the run history: what it was asked, each tool
 * call and what came back, and its answer. Secrets were redacted before the
 * run was stored; text that could not be redacted reads "Withheld". Each part
 * says where it came from (its stored provenance), and a run whose content is
 * withheld, not stored, cut, or whose steps cannot be told apart says so in
 * words: withheld is not empty, and "can't tell" is not "none".
 */
export function RunDetails({ runId }: { runId: string }) {
  const { run, error, isLoading } = useRun(runId);
  if (isLoading) return <Skeleton className="h-20 rounded-lg" />;
  if (error != null)
    return (
      <p className="text-destructive text-sm" role="alert">
        I can&apos;t read this run: {error.message}
      </p>
    );
  if (!run) return null;
  const body = (run.body ?? {}) as Body;
  // Three states never collapsed into one: content that is gone (withheld),
  // content never kept (not stored), and a turn that cannot be told apart
  // (can't tell). None of them reads as "nothing happened".
  if (body.withheld)
    return (
      <Notice testId="run-note-withheld" title="Withheld">
        {`${body.withheld}. The run happened; its content cannot be shown.`}
      </Notice>
    );
  if (body.not_stored)
    return (
      <Notice testId="run-note-not-stored" title="Content not stored">
        {body.not_stored}
      </Notice>
    );
  const steps = (body.messages ?? []).slice(1);
  const redactionFailed = JSON.stringify(body).includes(WITHHELD_MARK);
  return (
    <div
      className="bg-card border-border flex w-full flex-col gap-3 rounded-lg border p-3 text-sm"
      data-testid="run-details"
    >
      {body.cut && (
        <Notice testId="run-note-cut" title="Shortened">
          {`This run was ${mb(body.cut.original_bytes)}, over the ${mb(body.cut.cap_bytes)} kept per run. Its longest parts were cut, and each cut says how much it removed.`}
        </Notice>
      )}
      {redactionFailed && (
        <Notice testId="run-note-redaction" title="Some text withheld">
          {`Text that could not be checked for secrets was not stored and reads "${WITHHELD_MARK}". It was not empty.`}
        </Notice>
      )}
      <Part label="Asked" source={SOURCE[promptSource(body)] ?? SOURCE.unknown}>
        {body.prompt ?? "Not recorded"}
      </Part>
      {body.turn_found === false ? (
        <Notice testId="run-note-turn-unknown" title="Steps unknown">
          I can&apos;t tell which messages in the conversation belong to this
          run (the conversation was rewritten after it), so none were kept. This
          is not the same as a run with no steps.
        </Notice>
      ) : steps.length === 0 ? (
        <p
          className="text-muted-foreground text-xs"
          data-testid="run-note-no-steps"
        >
          No tool calls: the assistant answered directly.
        </p>
      ) : (
        steps.map((m, i) =>
          m.tool_calls?.length ? (
            m.tool_calls.map((call, j) => (
              <Part
                key={`${i}-${j}`}
                label={`Tool call: ${call.name ?? "?"}`}
                source={SOURCE[m.provenance ?? "assistant"]}
                mono
              >
                {JSON.stringify(call.args ?? {}, null, 2)}
              </Part>
            ))
          ) : m.type === "tool" || m.role === "tool" ? (
            <Part
              key={i}
              label={`Result: ${m.name ?? "tool"}`}
              source={SOURCE[m.provenance ?? "untrusted_tool_output"]}
              mono
            >
              {text(m.content)}
            </Part>
          ) : null,
        )
      )}
      <Part label="Answer" source={SOURCE.assistant}>
        {answer(body.reply, run.error)}
      </Part>
    </div>
  );
}

function Notice({
  testId,
  title,
  children,
}: {
  testId: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="bg-muted border-border rounded-md border p-2 text-sm"
      role="note"
      data-testid={testId}
    >
      <span className="font-medium">{title}. </span>
      <span className="text-muted-foreground">{children}</span>
    </div>
  );
}

function answer(reply?: string, error?: string | null): string {
  if (reply) return reply;
  if (error) return `No answer: ${error}`;
  return "No answer";
}

function Part({
  label,
  source,
  mono,
  children,
}: {
  label: string;
  source?: string;
  mono?: boolean;
  children: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-muted-foreground text-xs">
        {label}
        {source && <span data-testid="run-source"> · {source}</span>}
      </span>
      <div
        className={
          mono
            ? "max-h-64 overflow-auto font-mono text-xs whitespace-pre-wrap"
            : "whitespace-pre-wrap"
        }
      >
        {children}
      </div>
    </div>
  );
}
