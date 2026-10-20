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
import { idFromName, quietHoursText } from "@/core/automations/wording";
import type { QuietHoursView } from "@/core/triggers/types";
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
  { value: "quiet", label: "Home, quietly (in the app only)" },
  { value: "local", label: "On this machine" },
];

function zones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["UTC", "America/New_York", "Europe/London"];
  }
}

function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** A blank automation: what "New automation" starts from. */
export function blankRule(): RuleDoc {
  return {
    id: "",
    name: "",
    type: "cron",
    enabled: true,
    match: { schedule: "0 9 * * 1-5", timezone: browserZone() },
    prompt: "",
    destination: "auto",
    urgent: false,
  };
}

const FIELD =
  "border-input bg-background text-foreground min-h-11 rounded-md border px-2 py-1.5 text-sm md:min-h-9";

/**
 * Create or edit one automation. Every save goes through the one validated
 * write path (POST or PUT /api/automations/rules), naming the version of the
 * rule file it was based on; the engine's reason for refusing is shown inline,
 * and the rules in force are untouched.
 */
export function RuleForm({
  initial,
  mode,
  version,
  writable,
  takenIds = [],
  quietHours,
  onSaved,
  onCancel,
}: {
  initial: RuleDoc;
  mode: "create" | "edit";
  version: string | null;
  writable: boolean;
  /** Ids already in use: a new automation's id is made free of them. */
  takenIds?: string[];
  quietHours?: QuietHoursView | null;
  onSaved?: (id: string) => void;
  onCancel?: () => void;
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
  // A new automation's id comes from its name (or the template's id), free
  // of the ids in use; an existing one's never changes (it keys its thread).
  const id =
    mode === "create"
      ? idFromName(rule.name?.trim() ? rule.name : initial.id, takenIds)
      : rule.id;

  const set = (patch: Partial<RuleDoc>) => {
    setSaved(false);
    setRule((r) => ({ ...r, ...patch }));
  };
  const setMatch = (patch: Record<string, unknown>) =>
    set({ match: { ...rule.match, ...patch } });
  const setType = (type: string) =>
    set({
      type,
      match:
        type === "cron"
          ? { timezone: timezone || browserZone() }
          : { event: "waiting-on-user" },
    });

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
    const body: RuleDoc = { ...rule, id, match, name: rule.name?.trim() ?? "" };
    save.mutate(
      { rule: body, version, create: mode === "create" },
      {
        onSuccess: () => {
          setSaved(true);
          onSaved?.(id);
        },
      },
    );
  };

  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={submit}
      aria-label={mode === "create" ? "New automation" : "Edit automation"}
      data-testid="rule-form"
    >
      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Name</span>
        <Input
          value={rule.name ?? ""}
          onChange={(e) => set({ name: e.target.value })}
          placeholder="Morning brief"
          maxLength={80}
          required={mode === "create"}
          aria-describedby="name-hint"
          data-testid="rule-name"
        />
        <span id="name-hint" className="text-muted-foreground text-xs">
          {mode === "create" ? (
            <>
              Saved as <span className="font-mono">{id}</span>, which keys its
              conversation and history and cannot change later.
            </>
          ) : (
            <>
              Its id stays <span className="font-mono">{rule.id}</span>.
            </>
          )}
        </span>
      </label>

      {mode === "create" && (
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-sm font-medium">Trigger</legend>
          <div className="flex flex-wrap gap-2">
            {[
              { value: "cron", label: "On a schedule" },
              { value: "watcher", label: "When a coding session changes" },
            ].map((option) => (
              <label
                key={option.value}
                className={cn(
                  "border-input flex min-h-11 cursor-pointer items-center gap-2 rounded-md border px-3 text-sm md:min-h-9",
                  rule.type === option.value && "border-primary bg-primary/10",
                )}
              >
                <input
                  type="radio"
                  name="trigger-type"
                  value={option.value}
                  checked={rule.type === option.value}
                  onChange={() => setType(option.value)}
                  className="accent-primary"
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {rule.type === "cron" && (
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-sm font-medium">When</legend>
          {raw ? (
            <label className="flex flex-col gap-1">
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
                className="font-mono"
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
              <div
                className="flex flex-wrap gap-1"
                role="group"
                aria-label="Days"
              >
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
                        "min-h-11 min-w-11 rounded-md border px-2 text-xs md:min-h-8 md:min-w-10",
                        on
                          ? "bg-primary text-primary-foreground border-primary"
                          : "border-input text-foreground-2 hover:bg-accent",
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
                placeholder="America/New_York"
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
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">When</span>
          <select
            className={cn(FIELD, "block w-full")}
            value={matchText(rule.match.event)}
            onChange={(e) => setMatch({ event: e.target.value })}
            aria-label="Watcher event"
          >
            {WATCHER_EVENTS.map((ev) => (
              <option key={ev.value} value={ev.value}>
                {ev.label}
              </option>
            ))}
          </select>
        </label>
      )}

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">What to do</span>
        <Textarea
          value={rule.prompt}
          onChange={(e) => set({ prompt: e.target.value })}
          rows={3}
          placeholder="Brief me on what is waiting."
          aria-describedby="prompt-hint"
          data-testid="rule-prompt"
        />
        <span id="prompt-hint" className="text-muted-foreground text-xs">
          What the assistant is asked each time. It can use:{" "}
          {(FIELDS[rule.type] ?? []).map((f) => `{${f}}`).join(", ") || "none"}
        </span>
      </label>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <label className="flex items-center gap-2 text-sm">
          Send
          <select
            className={FIELD}
            value={rule.destination}
            onChange={(e) => set({ destination: e.target.value })}
            aria-label="Destination"
          >
            {DESTINATIONS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm md:min-h-0">
          <input
            type="checkbox"
            checked={Boolean(rule.urgent)}
            onChange={(e) => set({ urgent: e.target.checked })}
            className="accent-primary size-4"
          />
          Urgent: may interrupt quiet hours
          <span className="text-muted-foreground">
            ({quietHoursText(quietHours, timezone)})
          </span>
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm md:min-h-0">
          <input
            type="checkbox"
            checked={rule.enabled}
            onChange={(e) => set({ enabled: e.target.checked })}
            className="accent-primary size-4"
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

      <div className="flex flex-wrap gap-2">
        <Button
          type="submit"
          disabled={!writable || !version || save.isPending}
          data-testid="rule-submit"
        >
          {mode === "create" ? "Create automation" : "Save changes"}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
