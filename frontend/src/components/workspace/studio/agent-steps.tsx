"use client";

import {
  BellIcon,
  CalendarIcon,
  CheckIcon,
  ClockIcon,
  CodeIcon,
  HandIcon,
  HomeIcon,
  InfoIcon,
  ListIcon,
  MailIcon,
  MoonIcon,
  PencilIcon,
  PlusIcon,
  SendIcon,
  ShuffleIcon,
  SparklesIcon,
  Trash2Icon,
  WandSparklesIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { AVATARS, avatarMeta, randomAvatar } from "@/core/agents";
import { allZones, browserZone, type Day } from "@/core/automations/schedule";
import { useSkills } from "@/core/skills/hooks";
import {
  DAY_SHORT,
  WEEK,
  asksFirst,
  clock12,
  countSelection,
  cronOf,
  editOf,
  nextRuns,
  recurrenceText,
  runText,
  usable,
  type AgentRuns,
  type AutonomyView,
  type ScheduleEdit,
  type SchedulePreset,
  type ToolCatalog,
} from "@/core/studio";

import type { ConfigPanel } from "./agent-config";
import type { AgentForm, SchedRow } from "./agent-form";
import type { InnerRef } from "./agent-wizard";
import { useStudioCopy } from "./copy";
import {
  Av,
  DraftedTag,
  Glyph,
  Mono,
  Pill,
  Spinner,
  Switch,
  skillLook,
  cx,
} from "./parts";
import { skillTitle } from "./skills-list";

// ---------------------------------------------------------------------------
// Step 1: Agent Setup
// ---------------------------------------------------------------------------

/** Wrap the textarea's selection in Markdown (the editor's toolbar). */
function useMarkdownTools(value: string, onChange: (v: string) => void) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const apply = (before: string, after = before, line = false) => {
    const el = ref.current;
    if (!el) return;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    let next: string;
    let caret: number;
    if (line) {
      const lineStart = value.lastIndexOf("\n", start - 1) + 1;
      next = value.slice(0, lineStart) + before + value.slice(lineStart);
      caret = end + before.length;
    } else {
      next =
        value.slice(0, start) +
        before +
        value.slice(start, end) +
        after +
        value.slice(end);
      caret = end + before.length;
    }
    onChange(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(caret, caret);
    });
  };
  return { ref, apply };
}

export function MarkdownToolbar({
  apply,
  extra,
}: {
  apply: (before: string, after?: string, line?: boolean) => void;
  extra?: React.ReactNode;
}) {
  const c = useStudioCopy().agent;
  return (
    <div className="tb" role="toolbar" aria-label={c.formatting}>
      <button type="button" aria-label={c.bold} onClick={() => apply("**")}>
        B
      </button>
      <button type="button" aria-label={c.italic} onClick={() => apply("_")}>
        <i>I</i>
      </button>
      <button
        type="button"
        aria-label={c.heading}
        onClick={() => apply("## ", "", true)}
      >
        H
      </button>
      <span className="sep" />
      <button
        type="button"
        aria-label={c.list}
        onClick={() => apply("- ", "", true)}
      >
        <ListIcon size={15} aria-hidden />
      </button>
      <button type="button" aria-label={c.code} onClick={() => apply("`")}>
        <CodeIcon size={15} aria-hidden />
      </button>
      {extra}
    </div>
  );
}

export function AgentSetupStep({
  form,
  patch,
  isNew,
  isLead,
  drafted,
  draftInfo,
  drafting,
  draftError,
  nameError,
  onDraft,
  onUndoDraft,
  saveLabel,
  inner,
}: {
  form: AgentForm;
  patch: (p: Partial<AgentForm>) => void;
  isNew: boolean;
  isLead: boolean;
  drafted: boolean;
  draftInfo: { dropped: string[] } | null;
  drafting: boolean;
  draftError: string | null;
  nameError: string | null;
  onDraft: () => void;
  onUndoDraft: () => void;
  saveLabel: string;
  inner: InnerRef;
}) {
  const c = useStudioCopy().agent;
  const [picker, setPicker] = useState(false);
  const meta = avatarMeta(form.avatar);
  const grid = useRef<HTMLDivElement>(null);
  const md = useMarkdownTools(form.instructions, (v) =>
    patch({ instructions: v }),
  );
  const counts = form.selection
    ? countSelection(form.selection)
    : { tools: 0, integrations: 0 };

  useEffect(() => {
    inner.current = { ...inner.current, picker, close: () => setPicker(false) };
    return () => {
      inner.current = { ...inner.current, picker: false };
    };
  }, [picker, inner]);

  const onGridKey = (e: React.KeyboardEvent) => {
    const keys: Record<string, number> = {
      ArrowRight: 1,
      ArrowLeft: -1,
      ArrowDown: 5,
      ArrowUp: -5,
    };
    if (!(e.key in keys)) return;
    e.preventDefault();
    const i = AVATARS.findIndex((a) => a.id === form.avatar);
    const nextAv =
      AVATARS[(i + keys[e.key]! + AVATARS.length) % AVATARS.length]!;
    patch({ avatar: nextAv.id });
    grid.current
      ?.querySelector<HTMLElement>(`[data-avatar-id="${nextAv.id}"]`)
      ?.focus();
  };

  return (
    <div className="s1" data-testid="agent-step-setup">
      <div className="panel avatar-card">
        <button
          type="button"
          className="av-opt"
          style={{ width: 112, height: 112 }}
          onClick={() => (isLead ? undefined : setPicker((p) => !p))}
          aria-label={c.changeAvatar(meta.name)}
          aria-expanded={isLead ? undefined : picker}
          disabled={isLead}
          data-testid="avatar-big"
        >
          {}
          <img src={`/avatars/${meta.id}.svg`} alt="" />
        </button>
        <div className="who">
          <b>{meta.name}</b> · {meta.tag}
          <div style={{ marginTop: 2 }}>{meta.blurb}</div>
        </div>
        {isLead ? null : (
          <div className="row">
            <button
              type="button"
              className="btn sm"
              onClick={() => setPicker((p) => !p)}
              aria-expanded={picker}
              data-testid="avatar-change"
            >
              {picker ? (
                <CheckIcon size={14} aria-hidden />
              ) : (
                <PencilIcon size={14} aria-hidden />
              )}
              {picker ? c.done : c.change}
            </button>
            <button
              type="button"
              className="btn sm"
              onClick={() => patch({ avatar: randomAvatar(form.avatar) })}
              data-testid="avatar-surprise"
            >
              <ShuffleIcon size={14} aria-hidden />
              {c.surprise}
            </button>
          </div>
        )}
        {picker ? (
          <div
            className="av-grid"
            role="radiogroup"
            aria-label={c.chooseAvatar}
            ref={grid}
            onKeyDown={onGridKey}
          >
            {AVATARS.map((a) => {
              const on = a.id === form.avatar;
              return (
                <button
                  key={a.id}
                  type="button"
                  className="av-opt"
                  role="radio"
                  aria-checked={on}
                  tabIndex={on ? 0 : -1}
                  title={`${a.name} · ${a.tag}`}
                  aria-label={`${a.name}, ${a.tag}`}
                  onClick={() => patch({ avatar: a.id })}
                  data-avatar-id={a.id}
                >
                  {}
                  <img src={`/avatars/${a.id}.svg`} alt="" />
                  {on ? (
                    <span className="ok">
                      <CheckIcon size={10} aria-hidden />
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        ) : null}
        <p className="help">
          {picker ? c.avatarKeys : isLead ? "" : c.avatarHelp(isNew)}
        </p>
      </div>

      <div className="stack">
        {isLead ? (
          <div className="note">
            <InfoIcon size={16} aria-hidden />
            <div>{c.leadReadOnly}</div>
          </div>
        ) : (
          <div className={cx("draft-box", drafted && "done")}>
            <label className="label" htmlFor="f-sentence">
              <SparklesIcon size={15} aria-hidden />
              {c.describe} <DraftedTag show={drafted} />
            </label>
            <div className="row" style={{ marginTop: 8 }}>
              <input
                id="f-sentence"
                className="input"
                placeholder={c.describePlaceholder}
                value={form.sentence}
                onChange={(e) => patch({ sentence: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.metaKey && !e.ctrlKey) {
                    e.preventDefault();
                    onDraft();
                  }
                }}
                maxLength={600}
                data-testid="agent-sentence"
              />
              <button
                type="button"
                className="btn emph"
                onClick={onDraft}
                aria-busy={drafting || undefined}
                disabled={drafting}
                data-testid="agent-draft"
              >
                {drafting ? (
                  <Spinner />
                ) : (
                  <WandSparklesIcon size={15} aria-hidden />
                )}
                {drafting ? c.drafting : drafted ? c.redraft : c.draft}
              </button>
            </div>
            {draftError ? (
              <div
                className="err"
                role="alert"
                style={{ marginTop: 6 }}
                data-testid="agent-draft-error"
              >
                {draftError}
              </div>
            ) : null}
            {drafted ? (
              <div
                className="drafted-note"
                role="status"
                data-testid="agent-drafted"
              >
                <CheckIcon size={16} aria-hidden />
                <div>
                  <b style={{ fontWeight: 600, color: "var(--foreground)" }}>
                    {c.draftedTitle}
                  </b>{" "}
                  {c.draftedBody(
                    counts.tools,
                    form.skills?.length ?? 0,
                    form.schedules.some((s) => !s.ruleId),
                    saveLabel,
                  )}{" "}
                  {draftInfo?.dropped.length
                    ? `${c.draftDropped(draftInfo.dropped)} `
                    : null}
                  <button
                    type="button"
                    className="link"
                    onClick={onUndoDraft}
                    data-testid="agent-undo-draft"
                  >
                    {c.undoDraft}
                  </button>
                </div>
              </div>
            ) : (
              <p className="help" style={{ marginTop: 8 }}>
                {c.draftHelp}
              </p>
            )}
          </div>
        )}

        <div className="field">
          <label className="label" htmlFor="f-name">
            {c.name} <DraftedTag show={drafted} />
          </label>
          <input
            id="f-name"
            className="input"
            style={{ maxWidth: 420 }}
            value={form.name}
            placeholder={c.namePlaceholder}
            maxLength={80}
            readOnly={isLead}
            onChange={(e) => patch({ name: e.target.value })}
            aria-invalid={nameError ? true : undefined}
            aria-describedby="f-name-help"
            data-testid="agent-name"
          />
          {nameError ? (
            <div className="err" id="f-name-help" role="alert">
              {nameError}
            </div>
          ) : (
            <p className="help" id="f-name-help">
              {c.nameHelp}
            </p>
          )}
        </div>

        {isLead ? null : (
          <div className="field">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <label className="label" htmlFor="f-ins">
                {c.instructions} <DraftedTag show={drafted} />
              </label>
              <span className="count" aria-live="polite">
                {c.count(form.instructions.length)}
              </span>
            </div>
            <div className="editor">
              <MarkdownToolbar
                apply={md.apply}
                extra={
                  <>
                    <span className="grow" />
                    <button
                      type="button"
                      style={{ fontWeight: 500 }}
                      onClick={onDraft}
                      disabled={drafting}
                    >
                      <WandSparklesIcon size={14} aria-hidden /> {c.improve}
                    </button>
                  </>
                }
              />
              <textarea
                id="f-ins"
                ref={md.ref}
                rows={10}
                maxLength={8000}
                placeholder={c.instructionsPlaceholder}
                value={form.instructions}
                onChange={(e) => patch({ instructions: e.target.value })}
                data-testid="agent-instructions"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3: Schedule
// ---------------------------------------------------------------------------

const COMMON_ZONES = [
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Kolkata",
  "Asia/Tokyo",
  "Australia/Sydney",
  "UTC",
];

function zoneOptions(current: string): string[] {
  const all = new Set([current, browserZone(), ...COMMON_ZONES]);
  return [...all, ...allZones().filter((z) => !all.has(z))];
}

interface EditorState extends ScheduleEdit {
  key: string | null;
  prompt: string;
  telegram: boolean;
  home: boolean;
}

export function AgentScheduleStep({
  form,
  patch,
  isLead,
  drafted,
  runs,
  inner,
}: {
  form: AgentForm;
  patch: (p: Partial<AgentForm>) => void;
  isLead: boolean;
  drafted: boolean;
  runs: AgentRuns | undefined;
  inner: InnerRef;
}) {
  const c = useStudioCopy();
  const a = c.agent;
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [lastDeleted, setLastDeleted] = useState<{
    row: SchedRow;
    index: number;
  } | null>(null);
  const list = form.schedules;

  useEffect(() => {
    inner.current = {
      ...inner.current,
      editor: !!editor,
      close: () => setEditor(null),
    };
    return () => {
      inner.current = { ...inner.current, editor: false };
    };
  }, [editor, inner]);

  const openNew = (
    preset: SchedulePreset = "weekdays",
    time = "09:00",
    day: Day = 1,
  ) =>
    setEditor({
      key: null,
      preset,
      time,
      days: [day],
      cron: "45 8 * * 1-5",
      timezone: browserZone(),
      prompt: "",
      telegram: form.notify.telegram,
      home: form.notify.home,
    });

  const openEdit = (row: SchedRow) =>
    setEditor({
      key: row.key,
      ...editOf(row.cron, row.timezone),
      prompt: row.prompt,
      telegram: row.telegram,
      home: row.home,
    });

  const commit = (e: EditorState) => {
    const cron = cronOf(e);
    if (e.key) {
      patch({
        schedules: list.map((r) =>
          r.key === e.key
            ? {
                ...r,
                cron,
                timezone: e.timezone,
                prompt: e.prompt,
                telegram: e.telegram,
                home: e.home,
                nextRun:
                  r.cron === cron && r.timezone === e.timezone
                    ? r.nextRun
                    : null,
              }
            : r,
        ),
      });
    } else {
      patch({
        schedules: [
          ...list,
          {
            key: `new-${Date.now()}`,
            ruleId: null,
            cron,
            timezone: e.timezone,
            prompt: e.prompt,
            name: "",
            telegram: e.telegram,
            home: e.home,
            enabled: true,
            nextRun: null,
            heldUntil: null,
          },
        ],
      });
    }
    setEditor(null);
  };

  const remove = (row: SchedRow) => {
    const index = list.findIndex((r) => r.key === row.key);
    setLastDeleted({ row, index });
    patch({ schedules: list.filter((r) => r.key !== row.key) });
  };

  const quiet = runs?.quiet_hours;
  return (
    <div data-testid="agent-step-schedule">
      <div className="row wrap" style={{ marginBottom: 14, gap: 12 }}>
        <div className="grow">
          <h3 className="sec-title">
            {a.whenTitle} <DraftedTag show={drafted} />
          </h3>
          <p className="sec-sub" style={{ margin: 0 }}>
            {isLead ? a.scheduleLead : a.whenSub}
          </p>
        </div>
        {list.length && !editor ? (
          <button
            type="button"
            className="btn"
            onClick={() => openNew()}
            data-testid="schedule-add"
          >
            <PlusIcon size={16} aria-hidden />
            {a.addSchedule}
          </button>
        ) : null}
      </div>

      {runs && !runs.engine_enabled ? (
        <div className="note" style={{ marginBottom: 12 }}>
          <InfoIcon size={16} aria-hidden />
          <div>{a.engineOff}</div>
        </div>
      ) : null}
      {runs && runs.engine_enabled && !runs.writable ? (
        <div className="note" style={{ marginBottom: 12 }}>
          <InfoIcon size={16} aria-hidden />
          <div>{a.notWritable}</div>
        </div>
      ) : null}

      {!list.length && !editor ? (
        <div className="empty" data-testid="schedule-empty">
          <div className="badge-wrap">
            <Av id={form.avatar} size={64} />
            <span className="ckb">
              <ClockIcon size={14} aria-hidden />
            </span>
          </div>
          <b style={{ fontSize: 15 }}>{a.noSchedule}</b>
          <p className="help" style={{ maxWidth: 420 }}>
            {a.noScheduleBody(form.name.trim() || a.thisAgent)}
          </p>
          <div
            className="row wrap"
            style={{ justifyContent: "center", gap: 8 }}
          >
            {(
              [
                ["weekdays", "09:00", 1],
                ["daily", "18:00", 1],
                ["weekly", "08:00", 1],
              ] as const
            ).map(([p, t, d], i) => (
              <button
                key={p}
                type="button"
                className="chip btnlike"
                onClick={() => openNew(p, t, d)}
                data-testid={`schedule-quick-${p}`}
              >
                <ClockIcon size={12} aria-hidden />
                {a.quick[i]}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="btn"
            style={{ marginTop: 4 }}
            onClick={() => openNew()}
            data-testid="schedule-add"
          >
            <PlusIcon size={16} aria-hidden />
            {a.addSchedule}
          </button>
        </div>
      ) : null}

      {list.map((row) =>
        editor?.key === row.key ? (
          <ScheduleEditor
            key={row.key}
            value={editor}
            onChange={setEditor}
            onCancel={() => setEditor(null)}
            onSave={commit}
          />
        ) : (
          <ScheduleCard
            key={row.key}
            row={row}
            onToggle={() =>
              patch({
                schedules: list.map((r) =>
                  r.key === row.key ? { ...r, enabled: !r.enabled } : r,
                ),
              })
            }
            onEdit={() => openEdit(row)}
            onDelete={() => remove(row)}
          />
        ),
      )}
      {editor && !editor.key ? (
        <>
          {list.length ? <div style={{ height: 10 }} /> : null}
          <ScheduleEditor
            value={editor}
            onChange={setEditor}
            onCancel={() => setEditor(null)}
            onSave={commit}
          />
        </>
      ) : null}

      {lastDeleted ? (
        <div
          className="note"
          style={{ marginTop: 12 }}
          role="status"
          data-testid="schedule-deleted"
        >
          <Trash2Icon size={16} aria-hidden />
          <div className="grow">
            {a.deleted(
              recurrenceText(lastDeleted.row.cron, lastDeleted.row.timezone),
            )}
          </div>
          <button
            type="button"
            className="link"
            onClick={() => {
              const next = [...form.schedules];
              next.splice(
                Math.min(lastDeleted.index, next.length),
                0,
                lastDeleted.row,
              );
              patch({ schedules: next });
              setLastDeleted(null);
            }}
          >
            {c.undo}
          </button>
        </div>
      ) : null}

      {quiet?.enabled ? (
        <div
          className="note"
          style={{ marginTop: 16 }}
          data-testid="quiet-hours"
        >
          <MoonIcon size={16} aria-hidden />
          <div>
            <b style={{ fontWeight: 600, color: "var(--foreground)" }}>
              {a.quiet(`${clock12(quiet.start)} – ${clock12(quiet.end)}`)}
            </b>{" "}
            {a.quietBody(clock12(quiet.end))}{" "}
            <Link className="link" href="/workspace/automations">
              {a.changeInSettings}
            </Link>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ScheduleCard({
  row,
  onToggle,
  onEdit,
  onDelete,
}: {
  row: SchedRow;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const a = useStudioCopy().agent;
  const what = recurrenceText(row.cron, row.timezone);
  const computed = nextRuns(row.cron, row.timezone, new Date(), 1)[0];
  const next = row.nextRun ? new Date(row.heldUntil ?? row.nextRun) : computed;
  return (
    <div
      className={cx("sched", !row.enabled && "off")}
      data-testid="schedule-card"
      data-cron={row.cron}
    >
      <span className="ck" aria-hidden>
        <ClockIcon size={18} />
      </span>
      <div className="grow">
        <div className="when">{what}</div>
        <div className="task">{row.prompt}</div>
        <div className="chips">
          {row.telegram ? (
            <span className="chip">
              <SendIcon size={12} aria-hidden />
              {a.telegram}
            </span>
          ) : null}
          {row.home ? (
            <span className="chip">
              <HomeIcon size={12} aria-hidden />
              {a.home}
            </span>
          ) : null}
          <span className="chip">
            <CalendarIcon size={12} aria-hidden />
            {row.enabled
              ? next
                ? a.nextAt(runText(next))
                : a.noUpcoming
              : a.pausedChip}
          </span>
        </div>
      </div>
      <div className="acts">
        <Switch
          checked={row.enabled}
          onChange={onToggle}
          label={a.pause(row.enabled, what)}
          testId="schedule-toggle"
        />
        <span style={{ width: 8 }} />
        <button
          type="button"
          className="icon-btn"
          aria-label={a.editSchedule}
          onClick={onEdit}
          data-testid="schedule-edit"
        >
          <PencilIcon size={16} aria-hidden />
        </button>
        <button
          type="button"
          className="icon-btn danger"
          aria-label={a.deleteSchedule}
          onClick={onDelete}
          data-testid="schedule-delete"
        >
          <Trash2Icon size={16} aria-hidden />
        </button>
      </div>
    </div>
  );
}

function CheckBox({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <label className="row" style={{ gap: 8, cursor: "pointer" }}>
      <span
        className={cx("check", checked && "on")}
        role="checkbox"
        tabIndex={0}
        aria-checked={checked}
        aria-label={label}
        onClick={onChange}
        onKeyDown={(e) => {
          if (e.key === " " || e.key === "Enter") {
            e.preventDefault();
            onChange();
          }
        }}
      >
        {checked ? <CheckIcon size={12} aria-hidden /> : null}
      </span>
      <span aria-hidden>{label}</span>
    </label>
  );
}

function ScheduleEditor({
  value,
  onChange,
  onCancel,
  onSave,
}: {
  value: EditorState;
  onChange: (v: EditorState) => void;
  onCancel: () => void;
  onSave: (v: EditorState) => void;
}) {
  const a = useStudioCopy().agent;
  const uid = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollIntoView({ block: "nearest" });
  }, []);
  const set = (p: Partial<EditorState>) => onChange({ ...value, ...p });
  const cron = cronOf(value);
  const runs = useMemo(
    () => (cron ? nextRuns(cron, value.timezone, new Date(), 3) : []),
    [cron, value.timezone],
  );
  const valid =
    !!cron &&
    (value.preset === "custom"
      ? /^\S+\s+\S+\s+\S+\s+\S+\s+\S+$/.test(cron)
      : runs.length > 0);
  const ready = valid && value.prompt.trim().length > 0;
  const presets: SchedulePreset[] = ["daily", "weekdays", "weekly", "custom"];

  return (
    <div
      className="sched-ed"
      role="group"
      aria-label={value.key ? a.editSchedule : a.newSchedule}
      ref={ref}
      data-testid="schedule-editor"
    >
      <div className="stack" style={{ gap: 14 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <b style={{ fontSize: 14.5 }}>
            {value.key ? a.editSchedule : a.newSchedule}
          </b>
          <button
            type="button"
            className="icon-btn"
            aria-label={a.closeEditor}
            onClick={onCancel}
          >
            <XIcon size={16} aria-hidden />
          </button>
        </div>
        <div
          className="seg"
          role="radiogroup"
          aria-label={a.repeat}
          onKeyDown={(e) => {
            const d =
              e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
            if (!d) return;
            e.preventDefault();
            const i = presets.indexOf(value.preset);
            const nextP = presets[(i + d + presets.length) % presets.length]!;
            set({ preset: nextP });
            (e.currentTarget as HTMLElement)
              .querySelector<HTMLElement>(`[data-preset="${nextP}"]`)
              ?.focus();
          }}
        >
          {presets.map((p) => (
            <button
              key={p}
              type="button"
              role="radio"
              aria-checked={value.preset === p}
              tabIndex={value.preset === p ? 0 : -1}
              onClick={() =>
                set({
                  preset: p,
                  cron: p === "custom" ? cron || value.cron : value.cron,
                })
              }
              data-preset={p}
            >
              {a.presets[p]}
            </button>
          ))}
        </div>
        <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
          {value.preset === "weekly" ? (
            <div className="field">
              <span className="label">{a.on}</span>
              <div className="days" role="group" aria-label={a.days}>
                {WEEK.map((d) => {
                  const on = value.days.includes(d);
                  return (
                    <button
                      key={d}
                      type="button"
                      aria-pressed={on}
                      onClick={() =>
                        set({
                          days: on
                            ? value.days.filter((x) => x !== d)
                            : [...value.days, d],
                        })
                      }
                      data-day={d}
                    >
                      {DAY_SHORT[d]}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}
          {value.preset === "custom" ? (
            <div className="field" style={{ width: 220 }}>
              <label className="label" htmlFor={`${uid}-cron`}>
                {a.cron} <span className="count">{a.cronHint}</span>
              </label>
              <input
                id={`${uid}-cron`}
                className="input"
                style={{ fontFamily: "var(--font-mono)" }}
                value={value.cron}
                onChange={(e) => set({ cron: e.target.value })}
                data-testid="schedule-cron"
              />
            </div>
          ) : (
            <div className="field">
              <label className="label" htmlFor={`${uid}-time`}>
                {a.at}
              </label>
              <input
                id={`${uid}-time`}
                type="time"
                className="input"
                style={{ width: 140 }}
                value={value.time}
                onChange={(e) => set({ time: e.target.value })}
                data-testid="schedule-time"
              />
            </div>
          )}
          <div className="field">
            <label className="label" htmlFor={`${uid}-tz`}>
              {a.timeZone}
            </label>
            <select
              id={`${uid}-tz`}
              className="select input"
              style={{ width: 250 }}
              value={value.timezone}
              onChange={(e) => set({ timezone: e.target.value })}
              data-testid="schedule-zone"
            >
              {zoneOptions(value.timezone).map((z) => (
                <option key={z} value={z}>
                  {z.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div
          className="readout"
          aria-live="polite"
          data-testid="schedule-readout"
        >
          <ClockIcon size={16} aria-hidden />
          <div className="grow">
            <b>{cron ? recurrenceText(cron, value.timezone) : a.pickDay}</b>
            <div className="help">
              {runs.length
                ? a.nextRuns(runs.map((r) => runText(r)).join(" · "))
                : value.preset === "custom"
                  ? valid
                    ? a.nextAfterSave
                    : a.cronHelp
                  : a.pickDay}
            </div>
          </div>
        </div>
        <div className="field">
          <label className="label" htmlFor={`${uid}-task`}>
            {a.whatTask}
          </label>
          <textarea
            id={`${uid}-task`}
            className="textarea"
            rows={2}
            maxLength={4000}
            placeholder={a.taskPlaceholder}
            value={value.prompt}
            onChange={(e) => set({ prompt: e.target.value })}
            data-testid="schedule-task"
          />
          <p className="help">{a.taskHelp}</p>
        </div>
        <div className="row wrap" style={{ gap: 18 }}>
          <span
            className="label"
            style={{ fontWeight: 400, color: "var(--muted-foreground)" }}
          >
            {a.sendTo}
          </span>
          <CheckBox
            checked={value.telegram}
            onChange={() => set({ telegram: !value.telegram })}
            label={a.telegram}
          />
          <CheckBox
            checked={value.home}
            onChange={() => set({ home: !value.home })}
            label={a.home}
          />
          <span className="grow" />
          <button type="button" className="btn ghost" onClick={onCancel}>
            {useStudioCopy().cancel}
          </button>
          <button
            type="button"
            className="btn solid"
            aria-disabled={ready ? undefined : true}
            onClick={() => (ready ? onSave(value) : undefined)}
            data-testid="schedule-save"
          >
            {value.key ? a.updateSchedule : a.addSchedule}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4: Notifications & review
// ---------------------------------------------------------------------------

export function AgentReviewStep({
  form,
  orig,
  patch,
  isNew,
  isLead,
  legacy,
  catalog,
  autonomy,
  telegram,
  onJump,
}: {
  form: AgentForm;
  orig: AgentForm;
  patch: (p: Partial<AgentForm>) => void;
  isNew: boolean;
  isLead: boolean;
  legacy: boolean;
  catalog: ToolCatalog | undefined;
  autonomy: AutonomyView | undefined;
  telegram: { enabled?: boolean; running?: boolean } | undefined;
  onJump: (step: number, panel?: ConfigPanel) => void;
}) {
  const c = useStudioCopy();
  const a = c.agent;
  const { skills } = useSkills();
  const selection = form.selection ?? {};
  const counts = countSelection(selection);
  const t3 = asksFirst(selection, catalog);
  const granted = (autonomy?.classes ?? []).filter((k) =>
    form.grants.includes(k.id),
  );
  const unreachable = (catalog?.integrations ?? [])
    .filter(
      (i) => (selection[i.id]?.length ?? 0) > 0 && i.status === "unreachable",
    )
    .map((i) => i.name);
  const firstNext = form.schedules
    .filter((s) => s.enabled)
    .map((s) =>
      s.nextRun
        ? new Date(s.heldUntil ?? s.nextRun)
        : nextRuns(s.cron, s.timezone, new Date(), 1)[0],
    )
    .filter((d): d is Date => !!d)
    .sort((x, y) => x.getTime() - y.getTime())[0];

  const checks: ["ok" | "w", string][] = [];
  if (!isLead)
    checks.push(
      form.instructions.trim().length > 40
        ? ["ok", a.cHasInstructions]
        : ["w", a.cShortInstructions],
    );
  if (!isLead)
    checks.push(
      legacy
        ? ["ok", a.cLegacyTools]
        : counts.tools
          ? ["ok", a.cTools(counts.tools, counts.integrations)]
          : ["w", a.cNoTools],
    );
  if (t3.length) checks.push(["w", a.cAsks(t3.length)]);
  if (unreachable.length)
    checks.push(["w", a.cUnreachable(c.and(unreachable))]);
  checks.push(
    firstNext ? ["ok", a.cNext(runText(firstNext))] : ["w", a.cNoSchedule],
  );

  const dirtyKey = (keys: (keyof AgentForm)[]) =>
    !isNew &&
    keys.some((k) => JSON.stringify(form[k]) !== JSON.stringify(orig[k]));

  return (
    <div className="s4" data-testid="agent-step-review">
      <div className="stack">
        {isLead ? null : (
          <div className="panel" style={{ padding: "4px 16px" }}>
            <h3 className="sec-title" style={{ paddingTop: 12 }}>
              {a.notifications}{" "}
              {dirtyKey(["notify"]) ? (
                <span className="dirty-dot" style={{ marginLeft: 4 }} />
              ) : null}
            </h3>
            <p className="help" style={{ marginBottom: 4 }}>
              {a.notifyHelp}
            </p>
            <div className="notif">
              <span className="ni" aria-hidden>
                <SendIcon size={16} />
              </span>
              <div className="grow">
                <div className="nt">
                  {a.nTelegram}{" "}
                  {telegram?.running ? (
                    <Pill tone="good" dot>
                      {a.status.connected}
                    </Pill>
                  ) : (
                    <Pill tone="muted">{a.telegramNotSetUp}</Pill>
                  )}
                </div>
                <div className="nd">{a.nTelegramD}</div>
              </div>
              <Switch
                checked={form.notify.telegram}
                onChange={() =>
                  patch({
                    notify: { ...form.notify, telegram: !form.notify.telegram },
                  })
                }
                label={a.nTelegram}
                testId="notify-telegram"
              />
            </div>
            <div className="notif">
              <span className="ni" aria-hidden>
                <HomeIcon size={16} />
              </span>
              <div className="grow">
                <div className="nt">{a.nHome}</div>
                <div className="nd">{a.nHomeD}</div>
              </div>
              <Switch
                checked={form.notify.home}
                onChange={() =>
                  patch({ notify: { ...form.notify, home: !form.notify.home } })
                }
                label={a.nHome}
                testId="notify-home"
              />
            </div>
            {(
              [
                [HandIcon, a.nWaiting, a.nWaitingD],
                [MailIcon, a.nEmail, a.nEmailD],
              ] as const
            ).map(([Icon, title, detail]) => (
              <div className="notif disabled" key={title}>
                <span className="ni" aria-hidden>
                  <Icon size={16} />
                </span>
                <div className="grow">
                  <div className="nt">
                    {title} <Pill tone="muted">{a.comingSoon}</Pill>
                  </div>
                  <div className="nd">{detail}</div>
                </div>
                <Switch
                  checked={false}
                  onChange={() => undefined}
                  label={title}
                  disabled
                  describedBy="studio-soon"
                />
              </div>
            ))}
            <span id="studio-soon" className="sr-only">
              {a.soonSr}
            </span>
          </div>
        )}

        <section className="summary" aria-label={a.summary}>
          <div className="sh">
            <ListIcon size={15} aria-hidden />
            {a.summary}
            <span className="grow" />
            <span
              style={{
                textTransform: "none",
                letterSpacing: 0,
                fontWeight: 400,
                fontSize: 12.5,
                color: "var(--muted-foreground)",
              }}
            >
              {isNew ? a.summaryNew : a.summaryDirty}
            </span>
          </div>
          <SummaryRow
            onJump={onJump}
            label={a.sAgent}
            step={1}
            dirty={dirtyKey(["avatar", "name", "sentence", "instructions"])}
          >
            <div className="line">
              <Av id={form.avatar} size={28} />
              <b>{form.name.trim() || a.untitled}</b>
              <span className="sm">
                {a.avatarName(avatarMeta(form.avatar).name)}
              </span>
            </div>
            {form.sentence.trim() ? (
              <div className="line sm">{form.sentence}</div>
            ) : null}
            {isLead ? null : (
              <div className="line sm">
                {a.instructionsCount(form.instructions.length)}
              </div>
            )}
          </SummaryRow>
          {isLead ? null : (
            <SummaryRow
              onJump={onJump}
              label={a.sIntegrations}
              step={2}
              panel="integrations"
              dirty={
                !isNew &&
                form.toolsTouched &&
                JSON.stringify(form.selection) !==
                  JSON.stringify(orig.selection)
              }
            >
              {legacy ? (
                <span className="sm">{a.cLegacyTools}</span>
              ) : (catalog?.integrations ?? []).filter(
                  (i) => (selection[i.id]?.length ?? 0) > 0,
                ).length ? (
                (catalog?.integrations ?? [])
                  .filter((i) => (selection[i.id]?.length ?? 0) > 0)
                  .map((i) => {
                    const on = new Set(selection[i.id]);
                    const asks = i.tools.filter(
                      (t) => t.tier === 3 && on.has(t.name),
                    ).length;
                    return (
                      <div className="line" key={i.id}>
                        <Mono integration={i} />
                        <span>{i.name}</span>
                        <span className="sm">
                          {a.sTools(on.size)}
                          {asks ? ` · ${a.sAsks(asks)}` : ""}
                          {!usable(i) ? ` · ${a.status[i.status]}` : ""}
                        </span>
                      </div>
                    );
                  })
              ) : (
                <span className="sm">{a.sNone}</span>
              )}
            </SummaryRow>
          )}
          {isLead ? null : (
            <SummaryRow
              onJump={onJump}
              label={a.sSkills}
              step={2}
              panel="skills"
              dirty={dirtyKey(["skills"])}
            >
              {form.skills === null ? (
                <span className="sm">{a.cardSkills(null)}</span>
              ) : form.skills.length ? (
                <div className="line">
                  {form.skills.map((name) => {
                    const look = skillLook(name, null, null);
                    const known = skills.find((s) => s.name === name);
                    return (
                      <span className="chip" key={name}>
                        <Glyph
                          icon={look.icon}
                          color={look.color}
                          size={11}
                          box={18}
                        />
                        {known ? skillTitle(name) : name}
                      </span>
                    );
                  })}
                </div>
              ) : (
                <span className="sm">{a.sNone}</span>
              )}
            </SummaryRow>
          )}
          <SummaryRow
            onJump={onJump}
            label={a.sOnItsOwn}
            step={2}
            panel="autonomy"
            dirty={
              !isNew &&
              [...form.grants].sort().join() !== [...orig.grants].sort().join()
            }
          >
            {granted.length ? (
              <>
                <div className="line">
                  {granted.map((k) => k.label).join(" · ")}
                </div>
                <div className="line sm">
                  {a.sAsksFirstLine(autonomy?.cap_per_run ?? 20, t3.length)}
                </div>
              </>
            ) : (
              <span className="sm">{a.sNothingOwn}</span>
            )}
          </SummaryRow>
          <SummaryRow
            onJump={onJump}
            label={a.sSchedule}
            step={3}
            dirty={
              !isNew &&
              JSON.stringify(
                form.schedules.map((s) => [
                  s.ruleId,
                  s.cron,
                  s.timezone,
                  s.prompt,
                  s.enabled,
                  s.telegram,
                  s.home,
                ]),
              ) !==
                JSON.stringify(
                  orig.schedules.map((s) => [
                    s.ruleId,
                    s.cron,
                    s.timezone,
                    s.prompt,
                    s.enabled,
                    s.telegram,
                    s.home,
                  ]),
                )
            }
          >
            {form.schedules.length ? (
              form.schedules.map((s) => (
                <div className="line" key={s.key}>
                  <ClockIcon size={14} aria-hidden />
                  <span className={s.enabled ? undefined : "sm"}>
                    {recurrenceText(s.cron, s.timezone)}
                    {s.enabled ? "" : a.pausedSuffix}
                  </span>
                </div>
              ))
            ) : (
              <span className="sm">{a.sChatOnly}</span>
            )}
          </SummaryRow>
          {isLead ? null : (
            <SummaryRow
              onJump={onJump}
              label={a.sAlerts}
              step={4}
              dirty={dirtyKey(["notify"])}
            >
              <div className="line">
                {[
                  form.notify.telegram && a.telegram,
                  form.notify.home && a.home,
                ]
                  .filter(Boolean)
                  .join(" · ") || <span className="sm">{a.sNone}</span>}
              </div>
            </SummaryRow>
          )}
        </section>
      </div>
      <aside className="stack">
        <div
          className="panel"
          style={{ padding: 16 }}
          data-testid="before-save"
        >
          <h3 className="sec-title" style={{ marginBottom: 10 }}>
            {a.beforeSave}
          </h3>
          <div className="checks">
            {checks.map(([k, t]) => (
              <div className="ci" key={t}>
                {k === "ok" ? (
                  <CheckIcon size={16} className="okc" aria-hidden />
                ) : (
                  <InfoIcon size={16} className="wc" aria-hidden />
                )}
                <span>{t}</span>
              </div>
            ))}
          </div>
        </div>
        {isLead ? null : (
          <div className="note">
            <BellIcon size={16} aria-hidden />
            <div>{a.notifyHelp}</div>
          </div>
        )}
      </aside>
    </div>
  );
}

function SummaryRow({
  label,
  step,
  panel,
  dirty,
  onJump,
  children,
}: {
  label: string;
  step: number;
  panel?: ConfigPanel;
  dirty: boolean;
  onJump: (step: number, panel?: ConfigPanel) => void;
  children: ReactNode;
}) {
  const c = useStudioCopy();
  return (
    <div
      className={cx("srow", dirty && "changed")}
      data-testid={`summary-${step}-${panel ?? "main"}`}
    >
      <div className="k">
        {label}
        {dirty ? <span className="dirty-dot" title={c.edited} /> : null}
      </div>
      <div className="v">{children}</div>
      <button
        type="button"
        className="link"
        onClick={() => onJump(step, panel)}
        aria-label={c.editLabel(label)}
      >
        <PencilIcon size={13} aria-hidden />
        {c.edit}
      </button>
    </div>
  );
}
