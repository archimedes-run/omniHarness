"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { useRun } from "@/core/run-history/hooks";

type Message = {
  type?: string;
  role?: string;
  name?: string;
  content?: unknown;
  tool_calls?: { name?: string; args?: unknown }[];
};

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
 * run was stored; text that could not be redacted reads "Withheld".
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
  const body = (run.body ?? {}) as {
    prompt?: string;
    messages?: Message[];
    reply?: string;
  };
  const steps = (body.messages ?? []).slice(1);
  return (
    <div
      className="bg-card border-border flex w-full flex-col gap-3 rounded-lg border p-3 text-sm"
      data-testid="run-details"
    >
      <Part label="Asked">{body.prompt ?? ""}</Part>
      {steps.map((m, i) =>
        m.tool_calls?.length ? (
          m.tool_calls.map((call, j) => (
            <Part
              key={`${i}-${j}`}
              label={`Tool call: ${call.name ?? "?"}`}
              mono
            >
              {JSON.stringify(call.args ?? {}, null, 2)}
            </Part>
          ))
        ) : m.type === "tool" || m.role === "tool" ? (
          <Part key={i} label={`Result: ${m.name ?? "tool"}`} mono>
            {text(m.content)}
          </Part>
        ) : null,
      )}
      <Part label="Answer">{answer(body.reply, run.error)}</Part>
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
  mono,
  children,
}: {
  label: string;
  mono?: boolean;
  children: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-muted-foreground text-xs">{label}</span>
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
