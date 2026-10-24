"use client";

import { PlusIcon } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAgents } from "@/core/agents/hooks";
import type { Template } from "@/core/automations/api";
import { useDeleteRule, useSetRuleEnabled } from "@/core/automations/hooks";
import {
  headline,
  nextRunText,
  quietHoursText,
  ruleName,
  ruleDocOf,
  ruleZone,
  runsAs,
  runWords,
  shortSchedule,
  when,
} from "@/core/automations/wording";
import { useTriggerRules, useTriggerRuns } from "@/core/triggers/hooks";
import type { RuleView, RulesView } from "@/core/triggers/types";
import { cn } from "@/lib/utils";

import { RuleForm, blankRule } from "./rule-form";
import { RunDetails } from "./run-details";

/** What the right-hand side shows: one automation, or the new-automation editor. */
export type AutomationSelection =
  | { kind: "rule"; id: string }
  | { kind: "new"; template?: Template }
  | null;

const TONE: Record<string, string> = {
  good: "text-success",
  info: "text-primary",
  bad: "text-destructive",
  muted: "text-muted-foreground",
};

/**
 * The Automations panel (Feature 006, Automations.dc.html): the list with
 * on/off state on the left; on the right, one automation with its History
 * and Edit tabs, or a blank editor for a new one. Every write goes through the
 * one validated write path (core/automations), naming the rule file version
 * it was based on.
 */
export function AutomationsBoard({
  selection,
  onSelect,
  templates,
}: {
  selection: AutomationSelection;
  onSelect: (next: AutomationSelection) => void;
  templates?: Template[];
}) {
  const { view, isLoading, error } = useTriggerRules();
  const rules = useMemo(() => view?.rules ?? [], [view]);
  // Who each automation runs as (Feature 006-F). Unreadable agents leave the
  // names as slugs, never "missing".
  const { agents, error: agentsError } = useAgents();
  const known = agentsError ? undefined : agents;
  // Nothing chosen: the first automation, as the board opens on one.
  const current: AutomationSelection =
    selection ?? (rules[0] ? { kind: "rule", id: rules[0].id } : null);

  return (
    <div
      className="flex min-h-full flex-col md:flex-row"
      data-testid="automations-board"
    >
      <nav
        aria-label="Automations"
        className="border-border flex shrink-0 flex-col gap-1 border-b px-2.5 py-3.5 md:w-[280px] md:border-r md:border-b-0"
      >
        <button
          type="button"
          onClick={() => onSelect({ kind: "new" })}
          className={cn(
            "border-border-strong text-foreground hover:bg-accent mb-2 flex min-h-11 items-center gap-1.5 rounded-lg border border-dashed px-3 text-left text-sm md:min-h-9",
            current?.kind === "new" && "bg-surface-raised",
          )}
          data-testid="new-automation"
          aria-pressed={current?.kind === "new"}
        >
          <PlusIcon className="size-3.5" aria-hidden />
          New automation
        </button>
        {isLoading && (
          <div className="flex flex-col gap-2" data-testid="rules-loading">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12 rounded-lg" />
            ))}
          </div>
        )}
        {view && rules.length === 0 && (
          <p
            className="text-muted-foreground px-3 py-2 text-sm"
            data-testid="no-rules"
          >
            No automations yet.
          </p>
        )}
        <ul className="flex flex-col gap-1">
          {rules.map((rule) => {
            const active = current?.kind === "rule" && current.id === rule.id;
            return (
              <li key={rule.id}>
                <button
                  type="button"
                  onClick={() => onSelect({ kind: "rule", id: rule.id })}
                  aria-current={active ? "true" : undefined}
                  className={cn(
                    "flex min-h-11 w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left",
                    active
                      ? "bg-surface-raised text-foreground"
                      : "text-foreground-2 hover:bg-accent",
                  )}
                  data-testid="rule"
                  data-rule={rule.id}
                  data-enabled={rule.enabled}
                >
                  <span className="min-w-0 flex-1">
                    <span
                      className={cn(
                        "block truncate text-sm",
                        active && "font-medium",
                      )}
                    >
                      {ruleName(rule)}
                    </span>
                    <span className="text-muted-foreground block truncate text-xs">
                      {shortSchedule(rule)}
                    </span>
                    <span
                      className={cn(
                        "block truncate text-xs",
                        runsAs(rule.agent, known).missing
                          ? "text-destructive"
                          : "text-muted-foreground",
                      )}
                      data-testid="rule-runs-as"
                    >
                      {runsAs(rule.agent, known).text}
                    </span>
                  </span>
                  <span
                    role="img"
                    aria-label={rule.enabled ? "On" : "Off"}
                    className={cn(
                      "size-2 shrink-0 rounded-full",
                      rule.enabled
                        ? "bg-success"
                        : "border-muted-foreground border",
                    )}
                  />
                </button>
              </li>
            );
          })}
        </ul>
        <div className="flex-1" />
        <p className="text-muted-foreground border-border mt-3 border-t px-3 pt-2.5 text-xs">
          Tip: in any chat, say “every weekday at 9, brief me” to create one.
        </p>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <Notices view={view} error={error} />
        {current?.kind === "new" && view && (
          <NewAutomation
            key={current.template?.template ?? "blank"}
            view={view}
            templates={templates}
            template={current.template}
            onPick={(template) => onSelect({ kind: "new", template })}
            onSaved={(id) => onSelect({ kind: "rule", id })}
            onCancel={() => onSelect(null)}
          />
        )}
        {current?.kind === "rule" && view && (
          <RuleDetail
            key={current.id}
            known={known}
            view={view}
            rule={rules.find((r) => r.id === current.id)}
            ruleId={current.id}
            onDeleted={() => onSelect(null)}
          />
        )}
      </div>
    </div>
  );
}

function Notices({ view, error }: { view?: RulesView; error: Error | null }) {
  return (
    <div className="flex flex-col gap-2 px-4 pt-4 empty:hidden md:px-7">
      {error != null && (
        <Alert variant="destructive" data-testid="unreadable">
          <AlertTitle>I cannot read the automations</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      )}
      {view && !view.engine_enabled && (
        <Alert data-testid="engine-disabled">
          <AlertTitle>The trigger engine is off</AlertTitle>
          <AlertDescription>
            These rules are loaded, and nothing runs them until
            trigger_engine.enabled is set.
          </AlertDescription>
        </Alert>
      )}
      {view?.rules_error && (
        <Alert variant="destructive" data-testid="rules-error">
          <AlertTitle>The rule file was not accepted</AlertTitle>
          <AlertDescription>
            The rules shown are the previous ones, still in force.{" "}
            {view.rules_error}
          </AlertDescription>
        </Alert>
      )}
      {view && !view.writable && view.not_writable_reason && (
        <Alert data-testid="not-writable">
          <AlertTitle>These rules cannot be edited here</AlertTitle>
          <AlertDescription>{view.not_writable_reason}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

function RuleDetail({
  known,
  view,
  rule,
  ruleId,
  onDeleted,
}: {
  known: { name: string; display_name?: string | null }[] | undefined;
  view: RulesView;
  rule: RuleView | undefined;
  ruleId: string;
  onDeleted: () => void;
}) {
  const toggle = useSetRuleEnabled();
  const [tab, setTab] = useState("history");
  if (!rule) {
    return (
      <div className="px-4 py-5 md:px-7">
        <Alert data-testid="no-such-rule">
          <AlertTitle>There is no automation called {ruleId}</AlertTitle>
          <AlertDescription>
            It may have been deleted or renamed.
          </AlertDescription>
        </Alert>
      </div>
    );
  }
  const name = ruleName(rule);
  return (
    <div
      className="flex flex-col"
      data-testid="rule-detail"
      data-rule={rule.id}
    >
      <div className="flex flex-wrap items-center gap-3 px-4 pt-5 md:px-7">
        <div className="min-w-0 flex-[1_1_260px]">
          <h2 className="text-lg font-semibold">{name}</h2>
          <p className="text-muted-foreground text-[13px]">{headline(rule)}</p>
          <p
            className={cn(
              "text-[13px]",
              runsAs(rule.agent, known).missing
                ? "text-destructive"
                : "text-foreground-2",
            )}
            data-testid="rule-detail-runs-as"
          >
            {runsAs(rule.agent, known).text}
          </p>
        </div>
        <span className="text-foreground-2 text-[13px]">
          {rule.enabled ? "On" : "Off"}
        </span>
        <Switch
          checked={rule.enabled}
          disabled={!view.writable || !view.version || toggle.isPending}
          aria-label={`${name} is ${rule.enabled ? "on" : "off"}`}
          onCheckedChange={(enabled) =>
            view.version &&
            toggle.mutate({ id: rule.id, enabled, version: view.version })
          }
          data-testid="rule-switch"
        />
      </div>
      {toggle.error != null && (
        <p
          className="text-destructive px-4 pt-2 text-xs md:px-7"
          data-testid="toggle-error"
        >
          {toggle.error.message} The rules in force have not changed.
        </p>
      )}
      <Tabs value={tab} onValueChange={setTab} className="gap-0">
        <TabsList
          variant="line"
          aria-label="Automation views"
          className="border-border h-auto w-full justify-start rounded-none border-b px-4 pt-4 md:px-7"
        >
          {["history", "edit"].map((value) => (
            <TabsTrigger
              key={value}
              value={value}
              className="data-[state=active]:border-primary text-muted-foreground data-[state=active]:text-foreground min-h-11 flex-none rounded-none border-0 border-b-2 border-transparent px-3 py-2 data-[state=active]:bg-transparent data-[state=active]:shadow-none md:min-h-9"
            >
              {value === "history" ? "History" : "Edit"}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="history">
          <History view={view} rule={rule} />
        </TabsContent>
        <TabsContent value="edit">
          <div className="max-w-[760px] px-4 py-6 md:px-7">
            <RuleForm
              mode="edit"
              version={view.version}
              writable={view.writable}
              quietHours={view.quiet_hours}
              initial={ruleDocOf(rule)}
            />
            {view.writable && (
              <DeleteRule id={rule.id} view={view} onDeleted={onDeleted} />
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function DeleteRule({
  id,
  view,
  onDeleted,
}: {
  id: string;
  view: RulesView;
  onDeleted: () => void;
}) {
  const remove = useDeleteRule();
  const [confirm, setConfirm] = useState(false);
  return (
    <section className="border-border mt-8 flex flex-col gap-2 border-t pt-5">
      {remove.error != null && (
        <p className="text-destructive text-sm" data-testid="delete-error">
          {remove.error.message}
        </p>
      )}
      {confirm ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="destructive"
            disabled={remove.isPending}
            onClick={() =>
              view.version &&
              remove.mutate(
                { id, version: view.version },
                { onSuccess: onDeleted },
              )
            }
          >
            Delete it
          </Button>
          <Button variant="ghost" onClick={() => setConfirm(false)}>
            Keep it
          </Button>
        </div>
      ) : (
        <Button
          variant="outline"
          className="self-start"
          onClick={() => setConfirm(true)}
        >
          Delete this automation
        </Button>
      )}
    </section>
  );
}

function Card({ label, children }: { label: string; children: string }) {
  return (
    <div className="bg-card border-border rounded-xl border px-3.5 py-3">
      <div className="text-muted-foreground text-xs">{label}</div>
      <div>{children}</div>
    </div>
  );
}

function History({ view, rule }: { view: RulesView; rule: RuleView }) {
  const runs = useTriggerRuns(rule.id);
  const [open, setOpen] = useState<string | null>(null);
  const zone = ruleZone(rule);
  const names = new Map(view.rules.map((r) => [r.id, ruleName(r)]));
  return (
    <div
      className="flex w-full max-w-[760px] flex-col gap-4 px-4 py-6 md:px-7"
      data-testid="history"
    >
      <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-3">
        <Card label="Next run">{nextRunText(rule)}</Card>
        <Card label="Last checked">
          {rule.last_evaluated_at
            ? when(rule.last_evaluated_at, zone)
            : rule.last_evaluated === "not-recorded"
              ? "Not recorded"
              : "Never"}
        </Card>
        <Card label="Quiet hours">
          {quietHoursText(view.quiet_hours, zone)}
        </Card>
      </div>
      {runs.error != null && (
        <Alert variant="destructive" data-testid="history-unreadable">
          <AlertTitle>I cannot read its history</AlertTitle>
          <AlertDescription>{runs.error.message}</AlertDescription>
        </Alert>
      )}
      {runs.isLoading && <Skeleton className="h-24 rounded-lg" />}
      {runs.view?.runs.length === 0 && (
        <p className="text-muted-foreground text-sm" data-testid="no-history">
          It has not run yet.
        </p>
      )}
      <ul>
        {runs.view?.runs.map((run) => {
          const words = runWords(run, zone, (id) => names.get(id) ?? id);
          return (
            <li
              key={run.event_id}
              className="border-border flex flex-wrap gap-3 border-t py-3"
              data-testid="run"
              data-kind={run.kind}
            >
              <span className="text-muted-foreground w-[130px] shrink-0">
                {when(run.at, zone)}
              </span>
              <span className="min-w-0 flex-[1_1_260px]">
                <span className={TONE[words.tone]}>{words.label}</span>
                {words.detail}
              </span>
              <span className="flex gap-3">
                {run.content === "stored" && run.run_id && (
                  <button
                    type="button"
                    className="text-primary underline underline-offset-2"
                    aria-expanded={open === run.run_id}
                    onClick={() =>
                      setOpen(open === run.run_id ? null : (run.run_id ?? null))
                    }
                  >
                    Details
                  </button>
                )}
                {run.thread_id && (
                  <Link
                    href={`/workspace/chats/${run.thread_id}`}
                    className="text-primary underline underline-offset-2"
                  >
                    Open thread
                  </Link>
                )}
              </span>
              {run.content === "not-stored" && (
                <span
                  className="text-muted-foreground w-full pl-[142px] text-xs"
                  data-testid="not-stored"
                >
                  Its full record is not stored (from before the run history, or
                  past its retention).
                </span>
              )}
              {open === run.run_id && run.run_id && (
                <RunDetails runId={run.run_id} />
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function NewAutomation({
  view,
  templates,
  template,
  onPick,
  onSaved,
  onCancel,
}: {
  view: RulesView;
  templates?: Template[];
  template?: Template;
  onPick: (template?: Template) => void;
  onSaved: (id: string) => void;
  onCancel: () => void;
}) {
  const initial = template
    ? { ...template.rule, name: template.rule.name ?? template.title }
    : blankRule();
  return (
    <div
      className="flex max-w-[760px] flex-col gap-5 px-4 py-5 md:px-7"
      data-testid="new-automation-editor"
    >
      <div>
        <h2 className="text-lg font-semibold">New automation</h2>
        <p className="text-muted-foreground text-[13px]">
          {template
            ? `Starting from “${template.title}”. Change anything before you save.`
            : "Start from scratch, or from one of these."}
        </p>
      </div>
      {templates && templates.length > 0 && (
        <div className="flex flex-wrap gap-2" aria-label="Start from">
          <Button
            type="button"
            size="sm"
            variant="outline"
            aria-pressed={!template}
            className={cn(!template && "bg-surface-raised")}
            onClick={() => onPick(undefined)}
          >
            Blank
          </Button>
          {templates.map((t) => (
            <Button
              key={t.template}
              type="button"
              size="sm"
              variant="outline"
              aria-pressed={template?.template === t.template}
              className={cn(
                template?.template === t.template && "bg-surface-raised",
              )}
              onClick={() => onPick(t)}
              data-testid="template"
            >
              {t.title}
            </Button>
          ))}
        </div>
      )}
      <RuleForm
        mode="create"
        version={view.version}
        writable={view.writable}
        quietHours={view.quiet_hours}
        takenIds={view.rules.map((r) => r.id)}
        initial={initial}
        onSaved={onSaved}
        onCancel={onCancel}
      />
    </div>
  );
}
