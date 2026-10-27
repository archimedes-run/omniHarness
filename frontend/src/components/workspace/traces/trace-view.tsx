"use client";

import {
  CheckCircle2Icon,
  ChevronRightIcon,
  CircleAlertIcon,
  CircleDotIcon,
  CircleXIcon,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  PageCard,
  PageColumn,
  PageHeader,
} from "@/components/workspace/page-kit";
import {
  formatCost,
  formatDuration,
  formatTokens,
  parseTrace,
  statusLabel,
  statusTone,
  stepDuration,
  stepTree,
  TraceNotFound,
  typeLabel,
  useTrace,
  withheldReason,
  type StatusTone,
  type Trace,
  type TraceStep,
} from "@/core/traces";
import { badgeFor, traceHref } from "@/core/verification";
import { cn } from "@/lib/utils";

import { VerificationDetails } from "../messages/verification-badge";

const TONE_CLASS: Record<StatusTone, string> = {
  success: "border-success/40 bg-success/10 text-success",
  warning: "border-warning/40 bg-warning/10 text-warning",
  danger: "border-destructive/40 bg-destructive/10 text-destructive",
  neutral: "border-border bg-surface-raised text-foreground-2",
};

const TONE_ICON = {
  success: CheckCircle2Icon,
  warning: CircleAlertIcon,
  danger: CircleXIcon,
  neutral: CircleDotIcon,
} as const;

export function StatusChip({ status }: { status: string }) {
  const tone = statusTone(status);
  const Icon = TONE_ICON[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONE_CLASS[tone],
      )}
    >
      <Icon className="size-3" aria-hidden="true" />
      {statusLabel(status)}
    </span>
  );
}

function TierChip({ tier }: { tier: number | null }) {
  if (tier === null) return null;
  return (
    <span
      className="border-border text-foreground-2 rounded border px-1.5 py-0.5 text-[11px] font-medium tabular-nums"
      title={
        tier === 1
          ? "Tier 1: read, silent"
          : tier === 2
            ? "Tier 2: reversible write, disclosed"
            : "Tier 3: needs your confirmation"
      }
    >
      Tier {tier}
    </span>
  );
}

function time(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
}

function StepRow({
  step,
  tree,
  depth,
}: {
  step: TraceStep;
  tree: Map<number, TraceStep[]>;
  depth: number;
}) {
  const [open, setOpen] = useState(false);
  const children = tree.get(step.index) ?? [];
  const hasDetail = !!(step.args ?? step.output);
  const duration = stepDuration(step);
  const detailId = `trace-step-${step.index}`;
  return (
    <li
      data-testid="trace-step"
      data-type={step.type}
      data-status={step.status}
    >
      <div
        className="flex flex-wrap items-center gap-2 py-2"
        style={{ paddingLeft: depth * 20 }}
      >
        {hasDetail ? (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={detailId}
            onClick={() => setOpen((v) => !v)}
            className="text-muted-foreground hover:text-foreground focus-visible:ring-ring rounded p-0.5 focus-visible:ring-2 focus-visible:outline-none"
          >
            <ChevronRightIcon
              className={cn("size-4 transition-transform", open && "rotate-90")}
              aria-hidden="true"
            />
            <span className="sr-only">
              {open ? "Hide" : "Show"} details of step {step.index + 1}
            </span>
          </button>
        ) : (
          <span className="size-5" aria-hidden="true" />
        )}
        <span className="text-muted-foreground w-24 shrink-0 text-xs">
          {typeLabel(step.type)}
        </span>
        <span className="text-foreground min-w-0 font-mono text-[13px] break-all">
          {step.name || "—"}
        </span>
        <TierChip tier={step.tier} />
        <StatusChip status={step.status} />
        <span className="text-muted-foreground ml-auto text-xs tabular-nums">
          {time(step.started_at)}
          {duration !== null && ` · ${formatDuration(duration)}`}
        </span>
      </div>
      {hasDetail && open && (
        <div
          id={detailId}
          className="bg-surface-raised text-foreground-2 mb-2 rounded-md p-3 text-xs"
          style={{ marginLeft: depth * 20 + 28 }}
        >
          {step.args && (
            <p className="break-all whitespace-pre-wrap">
              <span className="text-foreground font-medium">Arguments: </span>
              {step.args}
            </p>
          )}
          {step.output && (
            <p className="mt-1 break-all whitespace-pre-wrap">
              <span className="text-foreground font-medium">Output: </span>
              {step.output}
            </p>
          )}
          {step.card_id && (
            <p className="mt-1">
              <span className="text-foreground font-medium">Card: </span>
              {step.card_id}
            </p>
          )}
        </div>
      )}
      {children.length > 0 && (
        <ul>
          {children.map((child) => (
            <StepRow
              key={child.index}
              step={child}
              tree={tree}
              depth={depth + 1}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-foreground text-sm font-medium tabular-nums">
        {value}
      </dd>
    </div>
  );
}

export function TraceBody({ trace }: { trace: Trace }) {
  const tree = stepTree(trace.steps);
  const badge = badgeFor(trace.verification);
  return (
    <div className="flex flex-col gap-5" data-testid="trace-view">
      <PageCard>
        <div className="flex flex-wrap items-center gap-2">
          <StatusChip status={trace.status} />
          {trace.thread_id && (
            <Link
              href={`/workspace/chats/${encodeURIComponent(trace.thread_id)}`}
              className="text-primary text-sm underline-offset-2 hover:underline"
            >
              Open the chat
            </Link>
          )}
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Duration" value={formatDuration(trace.duration_ms)} />
          <Stat label="Model" value={trace.model ?? "—"} />
          <Stat
            label="Tokens (in / out)"
            value={`${formatTokens(trace.tokens.input)} / ${formatTokens(trace.tokens.output)}`}
          />
          <Stat label="Estimated cost" value={formatCost(trace.cost_usd)} />
          <Stat label="Model calls" value={String(trace.llm_calls)} />
          <Stat label="Steps" value={String(trace.steps.length)} />
          <Stat label="Retries" value={String(trace.retries)} />
          <Stat label="Cards" value={String(trace.cards.length)} />
        </dl>
        {(Boolean(trace.resumed_from?.run_id) || trace.resumes.length > 0) && (
          <div className="text-foreground-2 mt-4 flex flex-col gap-1 text-sm">
            {trace.resumed_from?.run_id && (
              <p>
                Resumed from{" "}
                <Link
                  className="text-primary underline-offset-2 hover:underline"
                  href={traceHref(trace.resumed_from.run_id)}
                >
                  the run that raised{" "}
                  {trace.resumed_from.card_ids.length === 1
                    ? "a card"
                    : `${trace.resumed_from.card_ids.length} cards`}
                </Link>
              </p>
            )}
            {trace.resumes.map((id, i) => (
              <p key={id}>
                Continued in{" "}
                <Link
                  className="text-primary underline-offset-2 hover:underline"
                  href={traceHref(id)}
                >
                  resume run {i + 1}
                </Link>
              </p>
            ))}
          </div>
        )}
      </PageCard>

      {(Boolean(trace.done_criteria) || trace.verification !== null) && (
        <section
          aria-labelledby="trace-verification"
          className="flex flex-col gap-2"
        >
          <h2
            id="trace-verification"
            className="flex items-center gap-2 text-[15px] font-semibold"
          >
            Verification
            {badge && (
              <StatusChip
                status={badge.tone === "success" ? "verified" : "unverified"}
              />
            )}
          </h2>
          <PageCard>
            {trace.verification ? (
              <VerificationDetails record={trace.verification} />
            ) : (
              <p className="text-foreground-2 text-sm">
                <span className="text-foreground font-medium">Done when: </span>
                {trace.done_criteria}
              </p>
            )}
          </PageCard>
        </section>
      )}

      <section aria-labelledby="trace-steps" className="flex flex-col gap-2">
        <h2 id="trace-steps" className="text-[15px] font-semibold">
          Steps
        </h2>
        <PageCard>
          {trace.steps.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              This run made no steps.
            </p>
          ) : (
            <ol className="divide-border divide-y">
              {(tree.get(-1) ?? []).map((step) => (
                <StepRow key={step.index} step={step} tree={tree} depth={0} />
              ))}
            </ol>
          )}
        </PageCard>
      </section>

      {trace.cards.length > 0 && (
        <section aria-labelledby="trace-cards" className="flex flex-col gap-2">
          <h2 id="trace-cards" className="text-[15px] font-semibold">
            Cards
          </h2>
          <PageCard>
            <ul className="divide-border divide-y">
              {trace.cards.map((card) => (
                <li
                  key={card.id}
                  className="flex flex-wrap items-center gap-2 py-2 text-sm"
                >
                  <span className="text-foreground font-mono text-[13px]">
                    {card.tool}
                  </span>
                  <TierChip tier={card.tier} />
                  <StatusChip status={card.outcome ?? "needs_confirmation"} />
                  <span className="text-muted-foreground ml-auto text-xs">
                    {card.id}
                  </span>
                </li>
              ))}
            </ul>
          </PageCard>
        </section>
      )}
    </div>
  );
}

export function TraceView({ runId }: { runId: string }) {
  const { run, error, isLoading } = useTrace(runId);
  const trace = run ? parseTrace(run.body) : null;
  const withheld = run ? withheldReason(run.body) : null;
  return (
    <PageColumn width="wide">
      <PageHeader
        title="Run trace"
        description="Each step this run took, the tools and cards, retries and cost. Statuses come from the run's events, never from the reply."
      />
      {isLoading && (
        <p className="text-muted-foreground text-sm">Loading the trace…</p>
      )}
      {error instanceof TraceNotFound && (
        <Alert data-testid="trace-missing">
          <AlertTitle>No trace for this run yet</AlertTitle>
          <AlertDescription>
            Traces are written when a run ends. If the run is still working,
            open this page again when it has finished.
          </AlertDescription>
        </Alert>
      )}
      {error && !(error instanceof TraceNotFound) && (
        <Alert variant="destructive">
          <AlertTitle>I cannot read this trace</AlertTitle>
          <AlertDescription>{String(error.message)}</AlertDescription>
        </Alert>
      )}
      {withheld && (
        <Alert data-testid="trace-withheld">
          <AlertTitle>This trace&apos;s content is withheld</AlertTitle>
          <AlertDescription>{withheld}</AlertDescription>
        </Alert>
      )}
      {run && !withheld && !trace && (
        <Alert>
          <AlertTitle>This run has no trace record</AlertTitle>
          <AlertDescription>It was stored without step data.</AlertDescription>
        </Alert>
      )}
      {trace && <TraceBody trace={trace} />}
    </PageColumn>
  );
}
