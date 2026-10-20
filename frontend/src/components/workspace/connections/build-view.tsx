"use client";

import { useQueryClient } from "@tanstack/react-query";
import { SparklesIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  PageCard,
  SectionHeading,
  TONE_TEXT,
} from "@/components/workspace/page-kit";
import {
  approveAndEnable,
  getApprovalPacket,
  discardBuilt,
  startBuild,
} from "@/core/mcp-studio/api";
import { useBuiltServers } from "@/core/mcp-studio/hooks";
import type { BuildStep, BuiltServer } from "@/core/mcp-studio/types";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

import { buildStateTone } from "./build-state";

const HOW = [
  ["You describe it", "One sentence is enough"],
  ["An agent builds and tests it", "In a sandbox, away from your data"],
  ["You approve its first run", "Keys stay hidden from the model"],
] as const;

/**
 * MCP Suite > Build (Feature 006 board "MCP-Suite"): describe a tool in words;
 * an agent builds it and tests it in a sandbox (with placeholder keys); you
 * approve its first real run, and only then is it turned on. Each server says
 * where it is in words: drafting, building, tests failed (and why), waiting
 * for your approval, turning on, enabled.
 */
export function BuildView({ selected }: { selected: string | null }) {
  const router = useRouter();
  const { servers, isLoading, error } = useBuiltServers();
  const current =
    servers?.find((s) => s.id === selected) ?? servers?.[0] ?? null;
  const select = (id: string) =>
    router.replace(`/workspace/connections?tab=build&server=${id}`);

  return (
    <div className="flex flex-col gap-[22px]">
      <Describe onStarted={select} />

      <SectionHeading className="mt-1">Your MCP servers</SectionHeading>
      {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
      {error != null && (
        <PageCard
          className="border-destructive"
          data-testid="built-unreadable"
          role="alert"
        >
          <div className="font-medium">
            {String(error).includes("503")
              ? "The MCP builder is off on this gateway"
              : "I can't tell what has been built"}
          </div>
          <p className="text-muted-foreground text-[13px]">{String(error)}</p>
        </PageCard>
      )}
      {servers?.length === 0 && (
        <p className="text-muted-foreground text-sm" data-testid="built-empty">
          Nothing built yet. Describe a tool above to build your first.
        </p>
      )}
      {servers && servers.length > 0 && current && (
        <div className="flex flex-wrap items-start gap-4">
          <nav
            aria-label="Built servers"
            className="bg-card border-border divide-border min-w-0 flex-[1_1_320px] divide-y overflow-hidden rounded-xl border"
          >
            {servers.map((s) => (
              <button
                key={s.id}
                type="button"
                aria-current={s.id === current.id ? "true" : undefined}
                onClick={() => select(s.id)}
                className={cn(
                  "flex w-full items-center gap-3 px-4 py-3.5 text-left",
                  s.id === current.id ? "bg-surface-raised" : "hover:bg-accent",
                )}
                data-testid="built-server"
                data-state={s.state ?? "unknown"}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-[13px]">
                    {s.name}
                  </span>
                  <span className="text-muted-foreground block text-xs">
                    {subtitle(s)}
                  </span>
                </span>
                <span
                  className={cn("text-xs", TONE_TEXT[buildStateTone(s.state)])}
                >
                  {shortState(s)}
                </span>
              </button>
            ))}
          </nav>
          <Detail key={current.id} server={current} />
        </div>
      )}
    </div>
  );
}

function subtitle(s: BuiltServer): string {
  const when = formatTimeAgo(s.created_at);
  const tools =
    s.tool_count == null
      ? ""
      : ` · ${s.tool_count} tool${s.tool_count === 1 ? "" : "s"}`;
  if (s.state === "drafting" || s.state === "building")
    return `Started ${when}`;
  if (s.state === "tests_failed") return `Build failed · ${when}`;
  return `Built ${when}${tools}`;
}

function shortState(s: BuiltServer): string {
  switch (s.state) {
    case "awaiting_approval":
      return "Needs approval";
    case "enabled":
      return "Live";
    case "tests_failed":
      return "Failed";
    default:
      return s.state_label ?? s.status;
  }
}

function Describe({ onStarted }: { onStarted: (id: string) => void }) {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [hidden, setHidden] = useState<string[]>([]);

  const submit = async () => {
    if (text.trim().length < 3) return;
    setBusy(true);
    setProblem(null);
    try {
      const started = await startBuild(text.trim());
      setText("");
      setHidden(started.secret_placeholders);
      await queryClient.invalidateQueries({ queryKey: ["builtServers"] });
      onStarted(started.server_id);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      aria-labelledby="build-new"
      className="bg-card border-border flex flex-col gap-4 rounded-2xl border px-6 py-[22px]"
    >
      <h2 id="build-new" className="text-[17px] font-semibold">
        Need a tool that doesn&apos;t exist yet?
      </h2>
      <form
        className="bg-background border-primary flex flex-wrap items-center gap-2.5 rounded-xl border px-3 py-2.5"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <SparklesIcon className="text-primary size-4" aria-hidden />
        <label className="min-w-0 flex-[1_1_360px]">
          <span className="sr-only">Describe the tool</span>
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Describe it, e.g. “check my Devpost submissions and their judging status”"
            className="placeholder:text-muted-foreground w-full bg-transparent outline-none"
            maxLength={1024}
          />
        </label>
        <Button
          type="submit"
          className="rounded-[9px] font-semibold max-md:min-h-11"
          disabled={busy || text.trim().length < 3}
        >
          {busy ? "Starting…" : "Build it"}
        </Button>
      </form>
      {hidden.length > 0 && (
        <p
          className="text-foreground-2 text-[13px]"
          data-testid="secrets-hidden"
        >
          Your description had {hidden.length === 1 ? "a key" : "keys"} in it:
          stored as {hidden.join(", ")}. The agent sees only{" "}
          {hidden.map((n, i) => (
            <span key={n}>
              {i > 0 && ", "}
              <code className="font-mono text-xs">{`{{secret:${n}}}`}</code>
            </span>
          ))}
          .
        </p>
      )}
      {problem && (
        <p className="text-destructive text-[13px]" role="alert">
          {problem}
        </p>
      )}
      <ol className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
        {HOW.map(([title, sub], i) => (
          <li key={title} className="flex gap-2.5">
            <span className="bg-surface-raised flex size-6 flex-none items-center justify-center rounded-full text-xs font-semibold">
              {i + 1}
            </span>
            <span>
              <span className="block font-medium">{title}</span>
              <span className="text-muted-foreground block text-[13px]">
                {sub}
              </span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

const MARK: Record<BuildStep["status"], { glyph: string; cls: string }> = {
  done: { glyph: "✓", cls: "text-success" },
  failed: { glyph: "✗", cls: "text-destructive" },
  waiting: { glyph: "●", cls: "text-warning" },
};

function Detail({ server }: { server: BuiltServer }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const tone = buildStateTone(server.state);

  const act = async (work: () => Promise<unknown>, after?: () => void) => {
    setBusy(true);
    setProblem(null);
    try {
      await work();
      after?.();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      setConfirming(false);
      void queryClient.invalidateQueries({ queryKey: ["builtServers"] });
      void queryClient.invalidateQueries({ queryKey: ["toolSources"] });
    }
  };

  return (
    <section
      aria-labelledby="built-detail"
      className="bg-card border-border flex min-w-0 flex-[2_1_420px] flex-col gap-3.5 rounded-xl border px-5 py-[18px]"
      data-testid="built-detail"
      data-state={server.state ?? "unknown"}
    >
      <div className="flex flex-wrap items-center gap-2.5">
        <h3
          id="built-detail"
          className="flex-1 font-mono text-[15px] font-normal"
        >
          {server.name}
        </h3>
        <span
          className={cn(
            "rounded-md border px-2 py-0.5 text-xs",
            TONE_TEXT[tone],
            tone === "warn"
              ? "border-warning/40"
              : tone === "bad"
                ? "border-destructive/40"
                : tone === "good"
                  ? "border-success/40"
                  : "border-border",
          )}
          data-testid="build-state"
        >
          {server.state_label ?? server.status}
        </span>
      </div>
      {server.description && (
        <p className="text-foreground-2">{server.description}</p>
      )}
      {server.state_reason && (
        <p
          className={cn(
            "text-[13px]",
            server.state === "tests_failed" || server.state === "turn_on_failed"
              ? "text-destructive"
              : "text-muted-foreground",
          )}
          data-testid="build-reason"
        >
          {server.state_reason}
        </p>
      )}
      {server.steps && server.steps.length > 0 && (
        <ol className="flex flex-col gap-2" data-testid="build-steps">
          {server.steps.map((step) => (
            <li
              key={step.text}
              className="flex gap-2.5"
              data-status={step.status}
            >
              <span className={MARK[step.status].cls} aria-hidden>
                {MARK[step.status].glyph}
              </span>
              <span className="sr-only">
                {step.status === "done"
                  ? "Done:"
                  : step.status === "failed"
                    ? "Failed:"
                    : "Waiting:"}
              </span>
              {step.text}
            </li>
          ))}
        </ol>
      )}
      {problem && (
        <p className="text-destructive text-[13px]" role="alert">
          {problem}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        {server.thread_id && (
          <Button asChild variant="outline" className="rounded-lg">
            <Link href={`/workspace/chats/${server.thread_id}`}>View log</Link>
          </Button>
        )}
        <Button asChild variant="outline" className="rounded-lg">
          <Link href={`/workspace/mcp/${server.id}`}>View code</Link>
        </Button>
        {confirming ? (
          <>
            <Button
              variant="destructive"
              className="rounded-lg"
              disabled={busy}
              onClick={() =>
                void act(
                  () => discardBuilt(server.id),
                  () => router.replace("/workspace/connections?tab=build"),
                )
              }
            >
              Discard {server.name}
            </Button>
            <Button
              variant="ghost"
              className="rounded-lg"
              onClick={() => setConfirming(false)}
            >
              Keep
            </Button>
          </>
        ) : (
          <Button
            variant="outline"
            className="rounded-lg"
            onClick={() => setConfirming(true)}
          >
            Discard
          </Button>
        )}
        {server.state === "awaiting_approval" && server.code_sha256 && (
          <Button
            className="rounded-lg font-semibold"
            disabled={busy}
            onClick={() =>
              void act(async () => {
                const packet = await getApprovalPacket(server.id);
                return approveAndEnable(
                  server.id,
                  packet.code_sha256,
                  packet.view_token,
                );
              })
            }
          >
            {busy ? "Turning on…" : "Approve and turn on"}
          </Button>
        )}
      </div>
    </section>
  );
}
