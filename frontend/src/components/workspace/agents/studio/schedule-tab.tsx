"use client";

import { useEffect, useId, useState } from "react";

import {
  DAY_NAMES,
  allZones,
  browserZone,
  presetCron,
  presetOf,
  type Day,
  type Preset,
  type PresetSchedule,
} from "@/core/automations/schedule";
import {
  useAgentRuns,
  useScheduleWrite,
  type AgentDraft,
  type AgentSchedule,
} from "@/core/studio";
import { cn } from "@/lib/utils";

import { draftedScheduleText } from "./agent-tabs";
import { useStudioCopy, type StudioCopy } from "./copy";
import { formatWhen } from "./runs";
import { TabPanel, fieldClass, outlineButton } from "./studio-frame";

type C = StudioCopy["agents"];

/** What the editor holds: the schedule, its zone and its delivery. */
interface Draft extends PresetSchedule {
  timezone: string;
  telegram: boolean;
  show_on_home: boolean;
}

function draftOf(s: AgentSchedule | null): Draft {
  return {
    ...presetOf(s?.schedule ?? "0 9 * * 1-5"),
    timezone: s?.timezone ?? browserZone(),
    telegram: s?.telegram ?? true,
    show_on_home: s?.show_on_home ?? true,
  };
}

const primaryOutline = cn(outlineButton, "border-primary text-primary");

/**
 * Schedule and alerts (Agent-Studio.dc.html; Feature 006-F). Each schedule is
 * a trigger rule that runs AS this agent, written through the Automations
 * write path: one row per schedule ("Weekdays at 6:00 PM · zone") with Edit,
 * and the two delivery toggles under it, which save at once. A drafted
 * schedule is only a suggestion until the person presses its button.
 */
export function ScheduleTab({
  isLead,
  agentId,
  suggested,
}: {
  isLead: boolean;
  agentId: string | null;
  /** A schedule the draft suggested. Shown; set up only by the person. */
  suggested: AgentDraft["schedule"];
}) {
  const c = useStudioCopy().agents;
  const { runs, error } = useAgentRuns(agentId);
  const write = useScheduleWrite(agentId);
  const [editing, setEditing] = useState<string | null>(null);
  // Bumped when a toggle's save fails, so the toggles show the server's
  // value again (they flip at once, before the save answers).
  const [resetKey, setResetKey] = useState(0);
  const version = runs?.rules_version ?? null;
  const canWrite = !!agentId && !!runs?.writable && !!version;
  const schedules = runs?.schedules ?? [];
  const adopted =
    !!suggested &&
    schedules.some(
      (s) =>
        s.schedule === suggested.cron &&
        (!suggested.timezone || s.timezone === suggested.timezone),
    );

  const save = (draft: Draft, ruleId: string | null) => {
    if (!version) return;
    const body = {
      schedule: presetCron(draft),
      timezone: draft.timezone,
      telegram: draft.telegram,
      show_on_home: draft.show_on_home,
      version,
    };
    write.mutate(
      ruleId ? { kind: "update", ruleId, body } : { kind: "create", body },
      { onSuccess: () => setEditing(null) },
    );
  };

  const toggle = (s: AgentSchedule, patch: Partial<AgentSchedule>) => {
    if (!version) return;
    write.mutate(
      {
        kind: "update",
        ruleId: s.rule_id,
        body: {
          schedule: s.schedule,
          timezone: s.timezone,
          telegram: patch.telegram ?? s.telegram,
          show_on_home: patch.show_on_home ?? s.show_on_home,
          enabled: s.enabled,
          version,
        },
      },
      { onError: () => setResetKey((k) => k + 1) },
    );
  };

  return (
    <TabPanel
      value="schedule"
      className="flex flex-col gap-3.5 outline-none"
    >
      {isLead ? (
        <p className="text-foreground-2 m-0">{c.scheduleLead}</p>
      ) : null}

      {suggested && !adopted ? (
        <div
          className="bg-card border-primary flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3"
          data-testid="schedule-suggested"
        >
          <div className="flex-[1_1_260px]">
            <p className="text-muted-foreground text-xs">{c.suggested}</p>
            <p className="mt-0.5 font-medium">
              {draftedScheduleText(suggested)}
            </p>
            <p className="text-muted-foreground mt-0.5 text-sm">
              {agentId ? c.suggestedScheduleHow : c.suggestedSaveFirst}
            </p>
          </div>
          {agentId ? (
            <button
              type="button"
              className={primaryOutline}
              disabled={!canWrite || write.isPending}
              onClick={() =>
                version &&
                write.mutate({
                  kind: "create",
                  body: {
                    schedule: suggested.cron,
                    timezone: suggested.timezone ?? browserZone(),
                    telegram: true,
                    show_on_home: true,
                    version,
                  },
                })
              }
              data-testid="schedule-adopt"
            >
              {c.setUpSuggested}
            </button>
          ) : null}
        </div>
      ) : null}

      {!agentId ? (
        <div data-testid="schedule-none">
          <p className="font-medium">{c.scheduleNone}</p>
          <p className="text-muted-foreground mt-0.5 text-sm">
            {c.saveAgentFirstSchedule}
          </p>
        </div>
      ) : error ? (
        <p
          className="text-destructive"
          role="alert"
          data-testid="schedule-none"
        >
          {c.runsUnreadable(error.message)}
        </p>
      ) : !runs ? (
        <p className="text-muted-foreground">…</p>
      ) : (
        <>
          {runs.rules_error ? (
            <p className="text-warning text-sm">{c.rulesUnreadable}</p>
          ) : null}
          {!runs.engine_enabled ? (
            <p className="text-warning text-sm">{c.engineOff}</p>
          ) : null}
          {!runs.writable ? (
            <p
              className="text-muted-foreground text-sm"
              data-testid="schedule-readonly"
            >
              {c.scheduleNotWritable}
            </p>
          ) : null}

          {schedules.length === 0 && editing !== "new" ? (
            <div
              className="bg-card border-border-strong flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3"
              data-testid="schedule-none"
            >
              <div className="flex-[1_1_260px]">
                <p className="font-medium">{c.scheduleNone}</p>
                <p className="text-muted-foreground mt-0.5 text-sm">
                  {c.scheduleNoneBody}
                </p>
              </div>
              <button
                type="button"
                className={outlineButton}
                disabled={!canWrite}
                onClick={() => setEditing("new")}
                data-testid="schedule-add"
              >
                {c.addSchedule}
              </button>
            </div>
          ) : null}

          <ul
            className="m-0 flex list-none flex-col gap-3.5 p-0"
            data-testid="schedule-list"
          >
            {schedules.map((s) =>
              editing === s.rule_id ? (
                <li key={s.rule_id}>
                  <ScheduleEditor
                    c={c}
                    initial={draftOf(s)}
                    busy={write.isPending}
                    onSave={(d) => save(d, s.rule_id)}
                    onCancel={() => setEditing(null)}
                    onDelete={() =>
                      version &&
                      write.mutate(
                        { kind: "delete", ruleId: s.rule_id, version },
                        { onSuccess: () => setEditing(null) },
                      )
                    }
                  />
                </li>
              ) : (
                <li
                  key={s.rule_id}
                  className="flex flex-col gap-2.5"
                  data-testid="schedule-row"
                  data-rule={s.rule_id}
                >
                  <div className="bg-card border-border-strong flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3">
                    <div className="min-w-0 flex-[1_1_260px]">
                      <p className="m-0" data-testid="schedule-when">
                        {draftedScheduleText({
                          cron: s.schedule,
                          timezone: s.timezone,
                        })}
                      </p>
                      <p className="text-muted-foreground m-0 text-sm">
                        {scheduleStatus(s, c)}
                      </p>
                    </div>
                    <button
                      type="button"
                      className={outlineButton}
                      disabled={!canWrite}
                      onClick={() => setEditing(s.rule_id)}
                      aria-label={c.editScheduleLabel(
                        draftedScheduleText({
                          cron: s.schedule,
                          timezone: s.timezone,
                        }),
                      )}
                      data-testid="schedule-edit"
                    >
                      {c.edit}
                    </button>
                  </div>
                  <Toggle
                    key={`telegram-${resetKey}`}
                    label={c.sendTelegram}
                    checked={s.telegram}
                    disabled={!canWrite || write.isPending}
                    onChange={(on) => toggle(s, { telegram: on })}
                    testId="schedule-telegram"
                  />
                  <Toggle
                    key={`home-${resetKey}`}
                    label={c.showOnHome}
                    checked={s.show_on_home}
                    disabled={!canWrite || write.isPending}
                    onChange={(on) => toggle(s, { show_on_home: on })}
                    testId="schedule-home"
                  />
                </li>
              ),
            )}
            {editing === "new" ? (
              <li>
                <ScheduleEditor
                  c={c}
                  initial={draftOf(null)}
                  busy={write.isPending}
                  isNew
                  onSave={(d) => save(d, null)}
                  onCancel={() => setEditing(null)}
                />
              </li>
            ) : null}
          </ul>
          {schedules.length > 0 && editing !== "new" ? (
            <button
              type="button"
              className={cn(outlineButton, "self-start")}
              disabled={!canWrite}
              onClick={() => setEditing("new")}
              data-testid="schedule-add"
            >
              {c.addAnotherSchedule}
            </button>
          ) : null}
        </>
      )}
      {write.error ? (
        <p
          className="text-destructive text-sm"
          role="alert"
          data-testid="schedule-error"
        >
          {c.scheduleNotSaved(write.error.message)}
        </p>
      ) : null}
    </TabPanel>
  );
}

function scheduleStatus(s: AgentSchedule, c: C): string {
  if (!s.enabled) return c.scheduleOff;
  if (s.error) return c.runsUnreadable(s.error);
  if (!s.next_run) return c.noSchedule;
  const next = c.nextAt(formatWhen(s.next_run, c));
  return s.held_until
    ? `${next} (${c.heldQuiet(formatWhen(s.held_until, c))})`
    : next;
}

function Toggle({
  label,
  checked,
  disabled,
  onChange,
  testId,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (on: boolean) => void;
  testId: string;
}) {
  // Flips at once; follows the server's value when it changes.
  const [on, setOn] = useState(checked);
  useEffect(() => setOn(checked), [checked]);
  return (
    <label className="flex min-h-11 items-center gap-2.5 md:min-h-0">
      <input
        type="checkbox"
        className="accent-primary size-[18px]"
        checked={on}
        disabled={disabled}
        onChange={(e) => {
          setOn(e.target.checked);
          onChange(e.target.checked);
        }}
        data-testid={testId}
      />
      {label}
    </label>
  );
}

const PRESETS: Preset[] = ["daily", "weekdays", "weekly", "custom"];

function ScheduleEditor({
  c,
  initial,
  busy,
  isNew = false,
  onSave,
  onCancel,
  onDelete,
}: {
  c: C;
  initial: Draft;
  busy: boolean;
  isNew?: boolean;
  onSave: (draft: Draft) => void;
  onCancel: () => void;
  onDelete?: () => void;
}) {
  const id = useId();
  const [draft, setDraft] = useState<Draft>(initial);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const zones = allZones();
  const zoneOptions = zones.includes(draft.timezone)
    ? zones
    : [draft.timezone, ...zones];

  return (
    <form
      className="bg-card border-primary flex flex-col gap-4 rounded-xl border px-4 py-4"
      aria-label={isNew ? c.newScheduleLabel : c.editScheduleTitle}
      onSubmit={(e) => {
        e.preventDefault();
        onSave(draft);
      }}
      data-testid="schedule-editor"
    >
      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="mb-2 text-sm font-medium">{c.when}</legend>
        <div
          className="flex flex-wrap gap-2"
          role="radiogroup"
          aria-label={c.when}
        >
          {PRESETS.map((p) => (
            <label
              key={p}
              className={cn(
                "border-border-strong flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border px-3 text-sm md:min-h-9",
                draft.preset === p && "border-primary bg-primary-subtle",
              )}
            >
              <input
                type="radio"
                name={`${id}-preset`}
                value={p}
                checked={draft.preset === p}
                onChange={() =>
                  set(
                    p === "custom" && draft.preset !== "custom"
                      ? { preset: p, cron: presetCron(draft) }
                      : { preset: p },
                  )
                }
                className="accent-primary"
                data-testid={`schedule-preset-${p}`}
              />
              {c.presets[p]}
            </label>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-3">
          {draft.preset === "weekly" ? (
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground text-xs">{c.day}</span>
              <select
                className={fieldClass}
                value={draft.day}
                onChange={(e) => set({ day: Number(e.target.value) as Day })}
                data-testid="schedule-day"
              >
                {DAY_NAMES.map((name, i) => (
                  <option key={name} value={i}>
                    {c.dayNames[i] ?? name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {draft.preset === "custom" ? (
            <label className="flex min-w-[220px] flex-1 flex-col gap-1 text-sm">
              <span className="text-muted-foreground text-xs">
                {c.cronLabel}
              </span>
              <input
                className={cn(fieldClass, "font-mono")}
                value={draft.cron}
                onChange={(e) => set({ cron: e.target.value })}
                required
                spellCheck={false}
                data-testid="schedule-cron"
              />
            </label>
          ) : (
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground text-xs">{c.time}</span>
              <input
                type="time"
                className={fieldClass}
                value={draft.time}
                onChange={(e) => set({ time: e.target.value })}
                required
                data-testid="schedule-time"
              />
            </label>
          )}
          <label className="flex min-w-[220px] flex-1 flex-col gap-1 text-sm">
            <span className="text-muted-foreground text-xs">{c.timeZone}</span>
            <select
              className={fieldClass}
              value={draft.timezone}
              onChange={(e) => set({ timezone: e.target.value })}
              data-testid="schedule-zone"
            >
              {zoneOptions.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="text-muted-foreground m-0 text-xs">
          {c.quietHoursInherit}
        </p>
      </fieldset>
      <fieldset className="m-0 flex flex-col gap-1 border-0 p-0">
        <legend className="mb-1 text-sm font-medium">{c.delivery}</legend>
        <Toggle
          label={c.sendTelegram}
          checked={draft.telegram}
          onChange={(on) => set({ telegram: on })}
          testId="schedule-editor-telegram"
        />
        <Toggle
          label={c.showOnHome}
          checked={draft.show_on_home}
          onChange={(on) => set({ show_on_home: on })}
          testId="schedule-editor-home"
        />
      </fieldset>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="submit"
          className={primaryOutline}
          disabled={busy}
          data-testid="schedule-save"
        >
          {busy ? c.saving : c.saveSchedule}
        </button>
        <button type="button" className={outlineButton} onClick={onCancel}>
          {c.cancelEdit}
        </button>
        <span className="flex-1" />
        {onDelete ? (
          confirmDelete ? (
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-sm">{c.deleteScheduleConfirm}</span>
              <button
                type="button"
                className={cn(
                  outlineButton,
                  "border-destructive text-destructive",
                )}
                disabled={busy}
                onClick={onDelete}
                data-testid="schedule-delete-confirm"
              >
                {c.deleteSchedule}
              </button>
              <button
                type="button"
                className={outlineButton}
                onClick={() => setConfirmDelete(false)}
              >
                {c.keepSchedule}
              </button>
            </span>
          ) : (
            <button
              type="button"
              className={cn(outlineButton, "text-destructive")}
              onClick={() => setConfirmDelete(true)}
              data-testid="schedule-delete"
            >
              {c.deleteSchedule}
            </button>
          )
        ) : null}
      </div>
    </form>
  );
}
