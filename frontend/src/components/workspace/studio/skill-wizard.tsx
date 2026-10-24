"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  CheckIcon,
  FileIcon,
  FlaskConicalIcon,
  InfoIcon,
  SparklesIcon,
  TargetIcon,
  Trash2Icon,
  UploadIcon,
  WandSparklesIcon,
  XIcon,
} from "lucide-react";
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { avatarIdFor, useAgents } from "@/core/agents";
import { useSkills } from "@/core/skills/hooks";
import {
  addSkillFile,
  composeSkillMd,
  createCustomSkill,
  draft,
  parseSkillMd,
  removeSkillFile,
  removeSkillTest,
  saveCustomSkill,
  saveSkillAppearance,
  skillSlug,
  supportPathFor,
  testSkill,
  useCustomSkill,
  useSkillFiles,
  useSkillStudio,
  type SavedSkillTest,
} from "@/core/studio";

import { MarkdownToolbar } from "./agent-steps";
import { agentTitle } from "./agents-list";
import { useStudioCopy } from "./copy";
import {
  Av,
  Glyph,
  GlyphIcon,
  SKILL_GLYPHS,
  Spinner,
  skillLook,
  cx,
} from "./parts";
import { skillTitle, usersOf } from "./skills-list";
import { useStudio } from "./studio";
import { VersionHistory } from "./version-history";
import {
  FootLeft,
  NextButton,
  SaveButton,
  WizardShell,
  useWizardShortcuts,
} from "./wizard-shell";

interface PendingFile {
  path: string;
  content: string;
  size: number;
}

interface SkillForm {
  title: string;
  when: string;
  body: string;
  icon: string;
  color: number;
  /** The doc's other frontmatter lines, kept verbatim. */
  rest: string[];
  pending: PendingFile[];
  removed: string[];
}

const FILE_LIMIT = 512_000;

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** The instructions as the agent will read them, previewed safely (text only). */
export function MarkdownPreview({ text }: { text: string }) {
  const inline = (line: string): ReactNode[] => {
    const out: ReactNode[] = [];
    const re = /(\*\*[^*]+\*\*|`[^`]+`|_[^_]+_)/g;
    let last = 0;
    let m: RegExpExecArray | null;
    let k = 0;
    while ((m = re.exec(line))) {
      if (m.index > last) out.push(line.slice(last, m.index));
      const t = m[0];
      if (t.startsWith("**"))
        out.push(<strong key={k++}>{t.slice(2, -2)}</strong>);
      else if (t.startsWith("`"))
        out.push(<code key={k++}>{t.slice(1, -1)}</code>);
      else out.push(<em key={k++}>{t.slice(1, -1)}</em>);
      last = m.index + t.length;
    }
    if (last < line.length) out.push(line.slice(last));
    return out;
  };
  const blocks: ReactNode[] = [];
  let list: { kind: "ol" | "ul"; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((x, i) => <li key={i}>{inline(x)}</li>);
    blocks.push(
      list.kind === "ol" ? (
        <ol key={blocks.length}>{items}</ol>
      ) : (
        <ul key={blocks.length}>{items}</ul>
      ),
    );
    list = null;
  };
  for (const raw of text.replace(/\r\n/g, "\n").split("\n")) {
    const ol = /^\d+\.\s+(.*)/.exec(raw);
    const ul = /^[-*]\s+(.*)/.exec(raw);
    if (ol || ul) {
      const kind = ol ? "ol" : "ul";
      if (list && list.kind !== kind) flush();
      list ??= { kind, items: [] };
      list.items.push((ol ?? ul)![1]!);
      continue;
    }
    flush();
    const h = /^#{1,6}\s+(.*)/.exec(raw);
    if (h) blocks.push(<h2 key={blocks.length}>{inline(h[1]!)}</h2>);
    else if (raw.trim()) blocks.push(<p key={blocks.length}>{inline(raw)}</p>);
  }
  flush();
  return <Fragment>{blocks}</Fragment>;
}

/** The Skill stepper (design 15-18): Details, Instructions, Files, Test. */
export function SkillWizard({
  id,
  initialStep,
}: {
  id: string | null;
  initialStep?: number;
}) {
  const c = useStudioCopy();
  const s = c.skill;
  const studio = useStudio();
  const queryClient = useQueryClient();
  const isNew = id === null;
  const { skills, isLoading: skillsLoading } = useSkills();
  const meta = isNew ? null : (skills.find((k) => k.name === id) ?? null);
  const isCustom = isNew || meta?.category === "custom";
  const readOnly = !isNew && !isCustom;
  const { skill: content } = useCustomSkill(!isNew && isCustom ? id : null);
  const { files } = useSkillFiles(!isNew && isCustom ? id : null);
  const { record } = useSkillStudio(isNew ? null : id);
  const { agents } = useAgents();

  const [orig, setOrig] = useState<SkillForm | null>(() =>
    isNew
      ? {
          title: "",
          when: "",
          body: "",
          icon: "star",
          color: 0,
          rest: [],
          pending: [],
          removed: [],
        }
      : null,
  );
  const [form, setForm] = useState<SkillForm | null>(orig);
  const [step, setStep] = useState(Math.min(4, Math.max(1, initialStep ?? 1)));
  const [reached, setReached] = useState(isNew ? 1 : 4);
  const [sentence, setSentence] = useState("");
  const [drafting, setDrafting] = useState<"when" | "body" | null>(null);
  const [note, setNote] = useState<{ text: string; bad: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState<null | (() => void)>(null);
  const [view, setView] = useState<"write" | "split" | "preview">("split");
  const [testQ, setTestQ] = useState("");
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const body = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (orig || isNew || !meta) return;
    if (isCustom && !content) return;
    if (!record) return;
    const doc = content
      ? parseSkillMd(content.content)
      : { name: meta.name, description: meta.description, body: "", rest: [] };
    const look = skillLook(meta.name, record.icon, record.color);
    const base: SkillForm = {
      title: skillTitle(meta.name),
      when: doc.description,
      body: doc.body,
      icon: look.icon,
      color: look.color,
      rest: doc.rest,
      pending: [],
      removed: [],
    };
    setOrig(base);
    setForm(base);
  }, [orig, isNew, meta, isCustom, content, record]);

  const stepDirty = useCallback(
    (n: number) => {
      if (!form || !orig || isNew) return false;
      if (n === 1)
        return (
          form.when !== orig.when ||
          form.icon !== orig.icon ||
          form.color !== orig.color
        );
      if (n === 2) return form.body !== orig.body;
      if (n === 3) return form.pending.length > 0 || form.removed.length > 0;
      return false;
    },
    [form, orig, isNew],
  );
  const dirty = [1, 2, 3].some(stepDirty);
  const started =
    isNew &&
    !!form &&
    !!(form.title.trim() || form.when.trim() || form.body.trim());
  const patch = (p: Partial<SkillForm>) => {
    setForm((f) => (f ? { ...f, ...p } : f));
    setSaveError(null);
  };
  const goList = useCallback(() => studio.go({ view: "skills" }), [studio]);

  /** Set once the person chose (Discard, or a save that went through): the
   * navigation that follows is not asked about again. */
  const bypass = useRef(false);
  const requestLeave = useCallback(
    (then: () => void) => {
      if (!bypass.current && (dirty || started)) setLeaving(() => then);
      else then();
    },
    [dirty, started],
  );
  useEffect(() => {
    studio.registerEditor({
      escape: () => false,
      requestLeave,
      dirty: () => dirty || started,
    });
    return () => studio.registerEditor(null);
  }, [studio, requestLeave, dirty, started]);

  const name = isNew ? skillSlug(form?.title ?? "") : (id ?? "");

  const runDraft = async (what: "when" | "body") => {
    if (!form) return;
    const seed =
      what === "when"
        ? form.when.trim() ||
          form.title.trim() ||
          form.body.trim().slice(0, 300)
        : sentence.trim();
    if (!seed) {
      setNote({ text: c.agent.draftNeedsSentence, bad: true });
      return;
    }
    setDrafting(what);
    setNote(null);
    try {
      const result = await draft("skill", {
        sentence: seed.slice(0, 600),
        name: form.title || name || null,
        body: form.body || null,
      });
      const d = result.skill!;
      if (what === "when") {
        patch({ when: d.description || form.when });
        studio.toast(s.draftedWhen);
      } else {
        patch({
          body: d.body || form.body,
          when: form.when.trim() ? form.when : d.description,
          title: form.title.trim() ? form.title : (d.name ?? ""),
        });
      }
    } catch (e) {
      setNote({ text: c.agent.draftFailed(errorText(e)), bad: true });
    } finally {
      setDrafting(null);
    }
  };

  const save = async (): Promise<boolean> => {
    if (!form || !orig || saving || readOnly) return false;
    if (!name) {
      setNameError(s.nameNeeded);
      setStep(1);
      return false;
    }
    if (!form.when.trim()) {
      setNameError(s.whenNeeded);
      setStep(1);
      return false;
    }
    if (!isNew && !dirty) return true;
    setSaving(true);
    setSaveError(null);
    try {
      const md = composeSkillMd({
        name,
        description: form.when.trim(),
        body: form.body,
        rest: form.rest,
      });
      if (isNew) await createCustomSkill(name, md, "manual");
      else if (form.when !== orig.when || form.body !== orig.body)
        await saveCustomSkill(name, md, content?.version ?? 0, "manual");
      if (isNew || form.icon !== orig.icon || form.color !== orig.color)
        await saveSkillAppearance(name, form.icon, form.color);
      for (const path of form.removed) await removeSkillFile(name, path);
      for (const f of form.pending) await addSkillFile(name, f.path, f.content);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["skills"] }),
        queryClient.invalidateQueries({ queryKey: ["agents"] }),
      ]);
      studio.toast(s.savedToast(form.title || skillTitle(name)));
      if (isNew) {
        bypass.current = true;
        studio.go({ view: "skill", id: name, step });
      } else {
        setOrig(null);
        setForm(null);
      }
      return true;
    } catch (e) {
      setSaveError(s.saveFailed(errorText(e)));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const goStep = (n: number) => {
    if (isNew && n > reached && n > step + 1) return;
    if (n > step && step === 1 && form && !name) {
      setNameError(s.nameNeeded);
      return;
    }
    setNameError(null);
    if (isNew) setReached((r) => Math.max(r, n));
    setStep(n);
  };

  useWizardShortcuts(
    () => void save(),
    () => {
      if (step < 4) goStep(step + 1);
    },
  );

  const addFiles = async (list: FileList | null) => {
    if (!list || !form) return;
    const next = [...form.pending];
    for (const file of Array.from(list)) {
      if (file.size > FILE_LIMIT) {
        studio.toast(s.uploadFailed(file.name, "larger than 500 KB"));
        continue;
      }
      const text = await file.text();
      if (text.includes("\u0000")) {
        studio.toast(s.notText(file.name));
        continue;
      }
      const path = supportPathFor(file.name);
      next.splice(0, next.length, ...next.filter((p) => p.path !== path), {
        path,
        content: text,
        size: file.size,
      });
    }
    patch({ pending: next });
  };

  const runTest = async () => {
    const message = testQ.trim();
    if (!message || testing || !name) return;
    setTesting(true);
    setTestError(null);
    try {
      await testSkill(name, message, 3, true);
      setTestQ("");
      await queryClient.invalidateQueries({
        queryKey: ["skills", "studio", name],
      });
    } catch (e) {
      setTestError(s.testFailed(errorText(e)));
    } finally {
      setTesting(false);
    }
  };

  const usedBy = useMemo(
    () => (meta ? usersOf(meta, agents) : []),
    [meta, agents],
  );

  if (!form || !orig) {
    const gone = !isNew && !skillsLoading && !meta;
    return (
      <div className="contents">
        <div className="m-body">
          <p className={gone ? "err" : "help"} role={gone ? "alert" : "status"}>
            {gone ? s.gone(id ?? "") : c.skills.loading}
          </p>
        </div>
      </div>
    );
  }

  const savedFiles = (files ?? []).filter(
    (f) => !form.removed.includes(f.path),
  );
  const allFiles = [
    ...savedFiles.map((f) => ({ path: f.path, size: f.size, pending: false })),
    ...form.pending.map((f) => ({ path: f.path, size: f.size, pending: true })),
  ];
  const mentioned = (path: string) => {
    const base = path.split("/").pop() ?? path;
    return form.body.includes(base);
  };
  const tests = record?.tests ?? [];
  const descriptionUnsaved = form.when !== orig.when;

  let stepBody: ReactNode;
  if (step === 1)
    stepBody = (
      <div className="s1" data-testid="skill-step-details">
        <div className="panel avatar-card">
          <Glyph icon={form.icon} color={form.color} size={34} className="lg" />
          <div className="who">
            <b>{s.icon}</b> · {s.iconHelp}
          </div>
          <div
            className="glyph-grid"
            role="radiogroup"
            aria-label={s.icon}
            onKeyDown={(e) => {
              const keys: Record<string, number> = {
                ArrowRight: 1,
                ArrowLeft: -1,
                ArrowDown: 6,
                ArrowUp: -6,
              };
              if (!(e.key in keys) || readOnly) return;
              e.preventDefault();
              const i = SKILL_GLYPHS.findIndex(([g]) => g === form.icon);
              const next =
                SKILL_GLYPHS[
                  (i + keys[e.key]! + SKILL_GLYPHS.length) % SKILL_GLYPHS.length
                ]![0];
              patch({ icon: next });
              (e.currentTarget as HTMLElement)
                .querySelector<HTMLElement>(`[data-glyph="${next}"]`)
                ?.focus();
            }}
          >
            {SKILL_GLYPHS.map(([g]) => (
              <button
                key={g}
                type="button"
                role="radio"
                aria-checked={g === form.icon}
                tabIndex={g === form.icon ? 0 : -1}
                aria-label={g}
                disabled={readOnly}
                onClick={() => patch({ icon: g })}
                data-glyph={g}
              >
                <GlyphIcon icon={g} />
              </button>
            ))}
          </div>
          <div className="tints" role="radiogroup" aria-label={s.colour}>
            {[0, 1, 2, 3, 4, 5, 6, 7].map((t) => (
              <button
                key={t}
                type="button"
                role="radio"
                className={`t-${t}`}
                aria-checked={t === form.color}
                aria-label={s.colourN(t + 1)}
                disabled={readOnly}
                onClick={() => patch({ color: t })}
              />
            ))}
          </div>
        </div>
        <div className="stack">
          {readOnly ? (
            <div className="note">
              <InfoIcon size={16} aria-hidden />
              <div>{s.readOnly}</div>
            </div>
          ) : null}
          <div className="field">
            <label className="label" htmlFor="f-sname">
              {s.name}
            </label>
            <input
              id="f-sname"
              className="input"
              style={{ maxWidth: 420 }}
              value={form.title}
              placeholder={s.namePlaceholder}
              readOnly={!isNew}
              maxLength={64}
              onChange={(e) => patch({ title: e.target.value })}
              aria-invalid={nameError ? true : undefined}
              data-testid="skill-name"
            />
            {nameError ? (
              <div className="err" role="alert">
                {nameError}
              </div>
            ) : isNew && name ? (
              <p className="help">
                <code>{name}</code>
              </p>
            ) : null}
          </div>
          <div className="draft-box">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <label className="label" htmlFor="f-when">
                <TargetIcon size={15} aria-hidden />
                {s.when}
              </label>
              {readOnly ? null : (
                <button
                  type="button"
                  className="btn sm emph"
                  onClick={() => void runDraft("when")}
                  disabled={!!drafting}
                  data-testid="skill-draft-when"
                >
                  {drafting === "when" ? (
                    <Spinner />
                  ) : (
                    <WandSparklesIcon size={14} aria-hidden />
                  )}
                  {s.draftWhen}
                </button>
              )}
            </div>
            <textarea
              id="f-when"
              className="textarea"
              style={{ marginTop: 8, background: "var(--card)" }}
              rows={3}
              maxLength={1000}
              placeholder={s.whenPlaceholder}
              value={form.when}
              readOnly={readOnly}
              onChange={(e) => patch({ when: e.target.value })}
              data-testid="skill-when"
            />
            <p className="help" style={{ marginTop: 8 }}>
              {s.whenHelp}
            </p>
            <div className="row wrap" style={{ gap: 6, marginTop: 8 }}>
              <span className="help">{s.good}</span>
              <span className="chip">{s.goodEx}</span>
              <span className="help">{s.vague}</span>
              <span className="chip">{s.vagueEx}</span>
            </div>
            {note ? (
              <p
                className={note.bad ? "err" : "help"}
                role={note.bad ? "alert" : "status"}
                style={{ marginTop: 8 }}
              >
                {note.text}
              </p>
            ) : null}
          </div>
          <div className="field">
            <span className="label">{s.usedBy}</span>
            <div className="row wrap" style={{ gap: 6 }}>
              {usedBy.length ? (
                usedBy.map((a) => (
                  <span className="chip" key={a.name}>
                    <Av id={avatarIdFor(a.name, a.avatar)} size={18} />
                    {agentTitle(a)}
                  </span>
                ))
              ) : (
                <span className="help">{s.usedByNone}</span>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  else if (step === 2)
    stepBody = (
      <div className="stack" data-testid="skill-step-instructions">
        {readOnly ? null : (
          <div className="draft-box">
            <label className="label" htmlFor="f-ssent">
              <SparklesIcon size={15} aria-hidden />
              {s.describe}
            </label>
            <div className="row" style={{ marginTop: 8 }}>
              <input
                id="f-ssent"
                className="input"
                value={sentence}
                maxLength={600}
                placeholder={s.describePlaceholder}
                onChange={(e) => setSentence(e.target.value)}
                data-testid="skill-sentence"
              />
              <button
                type="button"
                className="btn emph"
                onClick={() => void runDraft("body")}
                disabled={!!drafting}
                data-testid="skill-draft"
              >
                {drafting === "body" ? (
                  <Spinner />
                ) : (
                  <WandSparklesIcon size={15} aria-hidden />
                )}
                {drafting === "body" ? c.agent.drafting : c.agent.draft}
              </button>
            </div>
            {note ? (
              <p
                className={note.bad ? "err" : "help"}
                role={note.bad ? "alert" : "status"}
                style={{ marginTop: 8 }}
              >
                {note.text}
              </p>
            ) : null}
          </div>
        )}
        <div className="field">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="label">{s.instructions}</span>
            <span className="count">{s.chars(form.body.length)}</span>
          </div>
          <div className="editor">
            <MarkdownToolbar
              apply={(before, after = before, line = false) => {
                const el = body.current;
                if (!el || readOnly) return;
                const a = el.selectionStart;
                const b = el.selectionEnd;
                const v = form.body;
                const lineStart = v.lastIndexOf("\n", a - 1) + 1;
                patch({
                  body: line
                    ? v.slice(0, lineStart) + before + v.slice(lineStart)
                    : v.slice(0, a) +
                      before +
                      v.slice(a, b) +
                      after +
                      v.slice(b),
                });
              }}
              extra={
                <>
                  <span className="sep" />
                  <button
                    type="button"
                    style={{ fontWeight: 500 }}
                    aria-label={s.insertFile}
                    disabled={readOnly || !allFiles.length}
                    onClick={() => {
                      const f =
                        allFiles.find((x) => !mentioned(x.path)) ?? allFiles[0];
                      if (f)
                        patch({
                          body: `${form.body}${form.body.endsWith("\n") || !form.body ? "" : "\n"}See \`${f.path.split("/").pop()}\`.\n`,
                        });
                    }}
                  >
                    <FileIcon size={14} aria-hidden /> {s.insertFile}
                  </button>
                  <span className="grow" />
                  <span
                    className="seg"
                    role="radiogroup"
                    aria-label={s.view}
                    style={{ height: 28 }}
                  >
                    {(["write", "split", "preview"] as const).map((v) => (
                      <button
                        key={v}
                        type="button"
                        role="radio"
                        aria-checked={view === v}
                        style={{ height: 26, padding: "0 10px", fontSize: 12 }}
                        onClick={() => setView(v)}
                      >
                        {v === "write"
                          ? s.write
                          : v === "split"
                            ? s.split
                            : s.previewTab}
                      </button>
                    ))}
                  </span>
                </>
              }
            />
            <div
              className="split"
              style={
                view !== "split" ? { gridTemplateColumns: "1fr" } : undefined
              }
            >
              {view !== "preview" ? (
                <textarea
                  ref={body}
                  aria-label={s.instructionsAria}
                  value={form.body}
                  readOnly={readOnly}
                  onChange={(e) => patch({ body: e.target.value })}
                  data-testid="skill-body"
                />
              ) : null}
              {view !== "write" ? (
                <div className="md" aria-label={s.previewAria} role="region">
                  <MarkdownPreview text={form.body} />
                </div>
              ) : null}
            </div>
          </div>
          <p className="help">{s.instructionsHelp}</p>
        </div>
      </div>
    );
  else if (step === 3)
    stepBody = (
      <div className="stack" data-testid="skill-step-files">
        <div>
          <h3 className="sec-title">{s.filesTitle}</h3>
          <p className="sec-sub" style={{ margin: 0 }}>
            {s.filesSub}
          </p>
        </div>
        {readOnly ? null : (
          <div
            className={cx("drop", over && "over")}
            role="button"
            tabIndex={0}
            aria-label={s.addFiles}
            onClick={() => fileInput.current?.click()}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                fileInput.current?.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              void addFiles(e.dataTransfer.files);
            }}
            data-testid="skill-drop"
          >
            <UploadIcon size={22} aria-hidden />
            <b style={{ fontWeight: 600 }}>{s.drop}</b>
            <span className="help">
              or <span className="link">{s.choose}</span> · {s.limit}
            </span>
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              onChange={(e) => void addFiles(e.target.files)}
              data-testid="skill-file-input"
            />
          </div>
        )}
        {allFiles.length ? (
          <div className="panel">
            {allFiles.map((f) => {
              const ext = (f.path.split(".").pop() ?? "").toLowerCase();
              const tint =
                ext === "md" ? 6 : ext === "py" ? 0 : ext === "csv" ? 7 : 5;
              return (
                <div className="file" key={f.path} data-testid="skill-file">
                  <span className={`fi t-${tint}`}>
                    {ext.slice(0, 3).toUpperCase() || "TXT"}
                  </span>
                  <div>
                    <div className="fn">{f.path.split("/").pop()}</div>
                    {f.pending ? <div className="help">{s.pending}</div> : null}
                  </div>
                  {mentioned(f.path) ? (
                    <span className="pill good">
                      <CheckIcon size={12} aria-hidden />
                      {s.mentioned}
                    </span>
                  ) : (
                    <span className="pill warn">{s.notMentioned}</span>
                  )}
                  <span className="fs">
                    {f.size < 1024
                      ? `${f.size} B`
                      : `${Math.round(f.size / 1024)} KB`}
                  </span>
                  {readOnly ? (
                    <span />
                  ) : (
                    <button
                      type="button"
                      className="icon-btn danger"
                      aria-label={s.removePending(
                        f.path.split("/").pop() ?? f.path,
                      )}
                      onClick={() =>
                        f.pending
                          ? patch({
                              pending: form.pending.filter(
                                (p) => p.path !== f.path,
                              ),
                            })
                          : patch({ removed: [...form.removed, f.path] })
                      }
                    >
                      <Trash2Icon size={15} aria-hidden />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="help">{s.noFiles}</p>
        )}
        {allFiles.some((f) => !mentioned(f.path)) ? (
          <div className="note">
            <InfoIcon size={16} aria-hidden />
            <div>
              {s.mentionNote}{" "}
              <button type="button" className="link" onClick={() => setStep(2)}>
                {s.mentionLink}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    );
  else
    stepBody = (
      <div className="stack" data-testid="skill-step-test">
        <div>
          <h3 className="sec-title">{s.testTitle}</h3>
          <p className="sec-sub" style={{ margin: 0 }}>
            {s.testSub}
          </p>
        </div>
        {isNew ? (
          <div className="note">
            <InfoIcon size={16} aria-hidden />
            <div>{s.testNeedsSave}</div>
          </div>
        ) : descriptionUnsaved ? (
          <div className="note">
            <InfoIcon size={16} aria-hidden />
            <div>{s.testUnsaved}</div>
          </div>
        ) : null}
        <div className="row">
          <input
            className="input"
            value={testQ}
            maxLength={2000}
            onChange={(e) => setTestQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void runTest();
              }
            }}
            placeholder={s.testPlaceholder}
            aria-label={s.testMessage}
            disabled={isNew}
            data-testid="skill-test-input"
          />
          <button
            type="button"
            className="btn"
            onClick={() => void runTest()}
            aria-disabled={!testQ.trim() || isNew || testing ? true : undefined}
            aria-busy={testing || undefined}
            data-testid="skill-test-run"
          >
            {testing ? <Spinner /> : <FlaskConicalIcon size={15} aria-hidden />}
            {testing ? s.trying : s.tryIt}
          </button>
        </div>
        {testError ? (
          <p className="err" role="alert">
            {testError}
          </p>
        ) : null}
        {tests.length ? (
          <div className="panel" data-testid="skill-tests">
            {tests.map((t) => (
              <TestRow
                key={t.message}
                test={t}
                onRemove={() =>
                  void removeSkillTest(name, t.message).then(() =>
                    queryClient.invalidateQueries({
                      queryKey: ["skills", "studio", name],
                    }),
                  )
                }
                onEditWhen={() => setStep(1)}
              />
            ))}
          </div>
        ) : (
          <div className="empty">
            <b>{s.noTests}</b>
            <span className="help">{s.noTestsBody}</span>
          </div>
        )}
        <div className="row wrap help" style={{ gap: 16 }}>
          <span className="row" style={{ gap: 6 }}>
            <span className="tries">
              <i className="hit" />
            </span>
            {s.legendHit}
          </span>
          <span className="row" style={{ gap: 6 }}>
            <span className="tries">
              <i />
            </span>
            {s.legendMiss}
          </span>
        </div>
      </div>
    );

  const steps = s.steps.map((label, i) => ({
    label,
    dirty: stepDirty(i + 1),
    drafted: false,
  }));
  const footer = (
    <>
      <FootLeft
        step={step}
        onPrev={() => goStep(step - 1)}
        onCancel={() => requestLeave(goList)}
        dirty={dirty}
      />
      <span className="grow" />
      {saveError ? (
        <span
          className="err"
          role="alert"
          style={{ maxWidth: 360 }}
          data-testid="wizard-save-error"
        >
          {saveError}
        </span>
      ) : null}
      {readOnly ? null : step < 4 && !isNew ? (
        <SaveButton
          label={s.save}
          onClick={() => void save()}
          dirty={dirty}
          saving={saving}
        />
      ) : null}
      {step < 4 ? (
        <NextButton label={s.steps[step]!} onClick={() => goStep(step + 1)} />
      ) : readOnly ? null : (
        <SaveButton
          label={s.save}
          onClick={() => void save()}
          dirty
          primary
          saving={saving}
        />
      )}
    </>
  );

  return (
    <div className="contents">
      <WizardShell
        kind={s.kind}
        backLabel={c.skills.title}
        onBack={() => requestLeave(goList)}
        isNew={isNew}
        step={step}
        reached={reached}
        steps={steps}
        onStep={goStep}
        identity={
          <Glyph icon={form.icon} color={form.color} size={20} box={40} />
        }
        title={form.title.trim() || s.untitled}
        badges={
          isNew ? (
            <span className="pill muted">{c.notSavedYet}</span>
          ) : readOnly ? (
            <span className="pill muted">{c.skills.builtIn}</span>
          ) : null
        }
        subtitle={form.when.trim() || s.startHint}
        dirty={dirty}
        leaving={
          leaving
            ? {
                steps: isNew
                  ? [s.steps[0]!]
                  : [1, 2, 3].filter(stepDirty).map((n) => s.steps[n - 1]!),
                saving,
                onKeep: () => setLeaving(null),
                onDiscard: () => {
                  const then = leaving;
                  setLeaving(null);
                  bypass.current = true;
                  then();
                },
                onSave: () => {
                  const then = leaving;
                  void save().then((ok) => {
                    if (ok) {
                      setLeaving(null);
                      bypass.current = true;
                      then();
                    }
                  });
                },
              }
            : null
        }
        footer={footer}
        testId="skill-wizard"
        history={
          isNew || readOnly || !id ? null : (
            <VersionHistory
              kind="skill"
              name={id}
              onRestored={() =>
                void Promise.all([
                  queryClient.invalidateQueries({ queryKey: ["skills"] }),
                ]).then(() => {
                  setOrig(null);
                  setForm(null);
                })
              }
            />
          )
        }
      >
        {stepBody}
      </WizardShell>
    </div>
  );
}

function TestRow({
  test,
  onRemove,
  onEditWhen,
}: {
  test: SavedSkillTest;
  onRemove: () => void;
  onEditWhen: () => void;
}) {
  const s = useStudioCopy().skill;
  const errors = test.tries.filter((t) => t.error).length;
  const verdict: [string, string] = !test.listed
    ? ["muted", s.doesntLoad]
    : test.total > 0 && test.loaded === test.total
      ? ["good", s.loads]
      : test.loaded === 0
        ? ["muted", s.doesntLoad]
        : ["warn", s.sometimes];
  return (
    <div
      className="test"
      data-testid="skill-test-row"
      data-loaded={test.loaded}
    >
      <div className="msg">“{test.message}”</div>
      <span className="tries" aria-hidden>
        {(test.tries.length
          ? test.tries
          : [{ loaded: false }, { loaded: false }, { loaded: false }]
        ).map((t, i) => (
          <i key={i} className={t.loaded ? "hit" : ""} />
        ))}
      </span>
      <span className={`pill ${verdict[0]}`} style={{ justifySelf: "start" }}>
        {verdict[1]} · {s.ofThree(test.loaded, test.total || 3)}
      </span>
      <button
        type="button"
        className="icon-btn"
        aria-label={s.removeTest}
        onClick={onRemove}
      >
        <XIcon size={14} aria-hidden />
      </button>
      {!test.listed ? (
        <div className="why">
          <InfoIcon size={13} aria-hidden />
          {s.notListed}
        </div>
      ) : test.loaded > 0 && test.loaded < test.total ? (
        <div className="why">
          <InfoIcon size={13} aria-hidden />
          {s.unsure}{" "}
          <button type="button" className="link" onClick={onEditWhen}>
            {s.editWhen}
          </button>
        </div>
      ) : errors ? (
        <div className="why">
          <InfoIcon size={13} aria-hidden />
          {s.tryErrors(errors)}
        </div>
      ) : null}
    </div>
  );
}
