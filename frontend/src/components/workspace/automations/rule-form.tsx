"use client";

import { useMemo, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { RuleDoc } from "@/core/automations/api";
import { useSaveRule } from "@/core/automations/hooks";
import {
  DAY_NAMES,
  type Day,
  fromCron,
  matchText,
  toCron,
} from "@/core/automations/schedule";
import { cn } from "@/lib/utils";

/** What each trigger type can put into a prompt (app/trigger_engine/config.py
 * AVAILABLE_FIELDS). The engine refuses any other {field}. */
const FIELDS: Record<string, string[]> = {
  cron: ["scheduled_at"],
  watcher: ["project", "session_id", "last_message", "state", "idle_reason"],
};

const WATCHER_EVENTS = [
  { value: "waiting-on-user", label: "A session is waiting on me" },
  { value: "session-failed", label: "A session failed" },
  { value: "idle", label: "A session finished or went quiet" },
];

const DESTINATIONS = [
  { value: "auto", label: "Automatic (Telegram when I'm away)" },
  { value: "remote", label: "Telegram" },
  { value: "quiet", label: "Quietly, in the app only" },
  { value: "local", label: "On this machine" },
];

function zones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["UTC", "America/New_York", "Europe/London"];
  }
}

const FIELD =
  "border-input bg-background text-foreground rounded-md border px-2 py-1.5 text-sm";

export function RuleForm({
  initial,
  mode,
  version,
  writable,
  onSaved,
}: {
  initial: RuleDoc;
  mode: "create" | "edit";
  version: string | null;
  writable: boolean;
  onSaved?: (id: string) => void;
}) {
  const save = useSaveRule();
  const [rule, setRule] = useState<RuleDoc>(initial);
  const schedule = matchText(initial.match.schedule);
  const simple = useMemo(() => fromCron(schedule), [schedule]);
  const [raw, setRaw] = useState(simple == null && rule.type === "cron");
  const [time, setTime] = useState(simple?.time ?? "09:00");
  const [days, setDays] = useState<Day[]>(simple?.days ?? [1, 2, 3, 4, 5]);
  const [cron, setCron] = useState(schedule);
  const [saved, setSaved] = useState(false);
  const timezone = matchText(rule.match.timezone);

  const set = (patch: Partial<RuleDoc>) => {
    setSaved(false);
    setRule((r) => ({ ...r, ...patch }));
  };
  const setMatch = (patch: Record<string, unknown>) =>
    set({ match: { ...rule.match, ...patch } });

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!version) return;
    const match =
      rule.type === "cron"
        ? {
            ...rule.match,
            schedule: raw ? cron.trim() : toCron({ time, days }),
          }
        : rule.match;
    save.mutate(
      { rule: { ...rule, match }, version, create: mode === "create" },
      {
        onSuccess: () => {
          setSaved(true);
          onSaved?.(rule.id);
        },
      },
    );
  };

  return (
    <form
      className="space-y-5"
      onSubmit={submit}
      aria-label="Automation"
      data-testid="rule-form"
    >
      {mode === "create" && (
        <label className="block space-y-1">
          <span className="text-sm font-medium">Name</span>
          <Input
            value={rule.id}
            onChange={(e) => set({ id: e.target.value })}
            aria-describedby="id-hint"
            required
          />
          <span id="id-hint" className="text-muted-foreground text-xs">
            A short id, like weekly-review. It cannot be changed later.
          </span>
        </label>
      )}

      {rule.type === "cron" && (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">When</legend>
          {raw ? (
            <label className="block space-y-1">
              <span className="text-muted-foreground text-xs">
                Cron expression (minute hour day month weekday)
              </span>
              <Input
                value={cron}
                onChange={(e) => {
                  setSaved(false);
                  setCron(e.target.value);
                }}
                aria-label="Cron expression"
              />
            </label>
          ) : (
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-sm">
                Time
                <Input
                  type="time"
                  value={time}
                  onChange={(e) => {
                    setSaved(false);
                    setTime(e.target.value);
                  }}
                  className="w-32"
                  aria-label="Time"
                />
              </label>
              <div className="flex gap-1" role="group" aria-label="Days">
                {DAY_NAMES.map((name, i) => {
                  const day = i as Day;
                  const on = days.includes(day);
                  return (
                    <button
                      key={name}
                      type="button"
                      aria-pressed={on}
                      onClick={() => {
                        setSaved(false);
                        setDays((d) =>
                          on ? d.filter((x) => x !== day) : [...d, day],
                        );
                      }}
                      className={cn(
                        "rounded-md border px-2 py-1 text-xs",
                        on
                          ? "bg-primary text-primary-foreground border-primary"
                          : "border-input text-muted-foreground hover:bg-muted",
                      )}
                    >
                      {name}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm">
              Time zone
              <Input
                list="tz-list"
                value={timezone}
                placeholder="UTC"
                onChange={(e) => setMatch({ timezone: e.target.value })}
                className="w-60"
                aria-label="Time zone"
              />
              <datalist id="tz-list">
                {zones().map((z) => (
                  <option key={z} value={z} />
                ))}
              </datalist>
            </label>
            <Button
              type="button"
              variant="link"
              size="sm"
              onClick={() => {
                if (!raw) setCron(toCron({ time, days }));
                setRaw(!raw);
              }}
            >
              {raw ? "Use time and days" : "Edit as cron"}
            </Button>
          </div>
        </fieldset>
      )}

      {rule.type === "watcher" && (
        <label className="block space-y-1">
          <span className="text-sm font-medium">When</span>
          <select
            className={cn(FIELD, "block w-full")}
            value={matchText(rule.match.event)}
            onChange={(e) => setMatch({ event: e.target.value })}
          >
            {WATCHER_EVENTS.map((ev) => (
              <option key={ev.value} value={ev.value}>
                {ev.label}
              </option>
            ))}
          </select>
        </label>
      )}

      <label className="block space-y-1">
        <span className="text-sm font-medium">What to ask</span>
        <Textarea
          value={rule.prompt}
          onChange={(e) => set({ prompt: e.target.value })}
          rows={3}
          aria-describedby="prompt-hint"
        />
        <span id="prompt-hint" className="text-muted-foreground text-xs">
          Can use:{" "}
          {(FIELDS[rule.type] ?? []).map((f) => `{${f}}`).join(", ") || "none"}
        </span>
      </label>

      <div className="flex flex-wrap items-center gap-6">
        <label className="flex items-center gap-2 text-sm">
          Send to
          <select
            className={FIELD}
            value={rule.destination}
            onChange={(e) => set({ destination: e.target.value })}
          >
            {DESTINATIONS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={Boolean(rule.urgent)}
            onChange={(e) => set({ urgent: e.target.checked })}
          />
          May interrupt quiet hours
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={rule.enabled}
            onChange={(e) => set({ enabled: e.target.checked })}
          />
          On
        </label>
      </div>

      {save.error != null && (
        <Alert variant="destructive" data-testid="rule-error">
          <AlertTitle>Not saved</AlertTitle>
          <AlertDescription>
            {save.error.message} The rules in force have not changed.
          </AlertDescription>
        </Alert>
      )}
      {saved && save.error == null && (
        <p className="text-muted-foreground text-sm" data-testid="rule-saved">
          Saved. The engine applies it on its next check of the rules.
        </p>
      )}

      <Button type="submit" disabled={!writable || !version || save.isPending}>
        {mode === "create" ? "Create automation" : "Save changes"}
      </Button>
    </form>
  );
}
