"use client";

import { useQueryClient } from "@tanstack/react-query";
import { SparkleIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useStudioCopy } from "@/components/workspace/agents/studio/copy";
import {
  DraftBar,
  DraftNote,
} from "@/components/workspace/agents/studio/draft-bar";
import {
  RailItem,
  RailNew,
  StudioFrame,
  StudioTabs,
  TabPanel,
  fieldClass,
  outlineButton,
  solidButton,
} from "@/components/workspace/agents/studio/studio-frame";
import {
  readItemParam,
  writeItemParam,
} from "@/components/workspace/agents/studio/url-item";
import { VersionHistory } from "@/components/workspace/agents/studio/version-history";
import { useAgents } from "@/core/agents";
import { useSkills } from "@/core/skills/hooks";
import type { Skill } from "@/core/skills/type";
import {
  addSkillFile,
  composeSkillMd,
  createCustomSkill,
  draft,
  parseSkillMd,
  saveCustomSkill,
  skillSlug,
  supportPathFor,
  useCustomSkill,
  useSkillFiles,
  type SkillDoc,
} from "@/core/studio";
import { cn } from "@/lib/utils";

import { MarkdownLite } from "./markdown-lite";

type Selection = { kind: "skill"; name: string } | { kind: "new" };
export type SkillTab = "details" | "instructions" | "files" | "test";

/** "project-status-format" -> "Project status format". */
export function skillTitle(name: string) {
  const words = name.replace(/[-_]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The Skills capsule panel: Skill Studio (Skill-Studio.dc.html). */
export function SkillStudio() {
  const c = useStudioCopy().skills;
  const { skills, isLoading, error } = useSkills();
  const [selection, setSelection] = useState<Selection | null>(() => {
    const item = readItemParam();
    if (item === "new") return { kind: "new" };
    return item ? { kind: "skill", name: item } : null;
  });
  const current: Selection =
    selection ??
    (skills[0] ? { kind: "skill", name: skills[0].name } : { kind: "new" });

  useEffect(() => {
    if (selection) {
      writeItemParam(selection.kind === "skill" ? selection.name : "new");
    }
  }, [selection]);
  useEffect(() => () => writeItemParam(null), []);

  const selected =
    current.kind === "skill"
      ? (skills.find((s) => s.name === current.name) ?? null)
      : null;

  const rail = (
    <>
      <RailNew
        label={c.newSkill}
        selected={current.kind === "new"}
        onClick={() => setSelection({ kind: "new" })}
      />
      {skills.map((skill) => (
        <RailItem
          key={skill.name}
          selected={current.kind === "skill" && current.name === skill.name}
          onClick={() => setSelection({ kind: "skill", name: skill.name })}
          testId={`studio-item-${skill.name}`}
        >
          {skillTitle(skill.name)}
        </RailItem>
      ))}
    </>
  );

  let body;
  if (isLoading) {
    body = <p className="text-muted-foreground p-7 text-sm">{c.loading}</p>;
  } else if (error) {
    body = (
      <p className="text-destructive p-7 text-sm" role="alert">
        {c.loadFailed(error.message)}
      </p>
    );
  } else if (current.kind === "skill" && !selected) {
    body = (
      <p
        className="text-muted-foreground p-7 text-sm"
        role="status"
        data-testid="studio-gone"
      >
        {c.gone(current.name)}
      </p>
    );
  } else {
    body = (
      <SkillEditor
        key={current.kind === "skill" ? current.name : "new"}
        skill={selected}
        onCreated={(name) => setSelection({ kind: "skill", name })}
      />
    );
  }

  return (
    <StudioFrame rail={rail} railLabel={c.railLabel} testId="skill-studio">
      {body}
    </StudioFrame>
  );
}

function useUsedBy(skill: Skill | null): string {
  const c = useStudioCopy();
  const { agents } = useAgents();
  if (!skill) return "";
  const names: string[] = [];
  if (skill.enabled) names.push(c.agents.leadName);
  for (const agent of agents) {
    const loads =
      agent.skills === null ? skill.enabled : agent.skills.includes(skill.name);
    if (loads)
      names.push(
        agent.display_name?.trim()
          ? agent.display_name.trim()
          : skillTitle(agent.name),
      );
  }
  return c.skills.usedBy(names);
}

function SkillEditor({
  skill,
  onCreated,
}: {
  skill: Skill | null;
  onCreated: (name: string) => void;
}) {
  const c = useStudioCopy().skills;
  const queryClient = useQueryClient();
  const isNew = skill === null;
  const isCustom = skill?.category === "custom";
  const readOnly = !isNew && !isCustom;
  const { skill: content, isLoading } = useCustomSkill(
    isCustom ? skill.name : null,
  );
  const initial: SkillDoc = useMemo(() => {
    if (content) return parseSkillMd(content.content);
    return {
      name: skill?.name ?? "",
      description: skill?.description ?? "",
      body: "",
      rest: [],
    };
  }, [content, skill]);
  const [title, setTitle] = useState("");
  const [doc, setDoc] = useState<SkillDoc>(initial);
  const [tab, setTab] = useState<SkillTab>("details");
  const [status, setStatus] = useState<
    | { kind: "idle" }
    | { kind: "saving" }
    | { kind: "saved" }
    | { kind: "error"; message: string }
  >({ kind: "idle" });
  useEffect(() => setDoc(initial), [initial]);
  const [fromDraft, setFromDraft] = useState(false);
  const usedBy = useUsedBy(skill);

  const patch = (next: Partial<SkillDoc>) => {
    setDoc((d) => ({ ...d, ...next }));
    setStatus({ kind: "idle" });
  };

  const slug = isNew ? skillSlug(title) : (skill?.name ?? "");
  const [drafting, setDrafting] = useState(false);
  const [draftNote, setDraftNote] = useState<{
    text: string;
    bad: boolean;
  } | null>(null);

  /** Draft for review; nothing is saved until Save skill. */
  async function runDraft(
    sentence: string,
    apply: (d: { description: string; body: string }) => void,
  ) {
    try {
      const result = await draft("skill", {
        sentence,
        name: isNew ? title : skill?.name,
        body: doc.body || null,
      });
      apply(result.skill!);
      setFromDraft(true);
      setDraftNote({ text: c.draftReady(result.model), bad: false });
    } catch (e) {
      setDraftNote({
        text: c.draftFailed(e instanceof Error ? e.message : String(e)),
        bad: true,
      });
    }
  }

  async function draftWhen() {
    const name = isNew ? title.trim() : skillTitle(skill?.name ?? "");
    if (!name && !doc.body.trim()) {
      setDraftNote({ text: c.draftWhenNeeds, bad: false });
      return;
    }
    setDrafting(true);
    await runDraft(`When should the skill "${name}" be used?`, (d) =>
      patch({ description: d.description || doc.description }),
    );
    setDrafting(false);
  }

  async function draftBody(sentence: string) {
    await runDraft(sentence, (d) =>
      patch({
        body: d.body || doc.body,
        description: doc.description.trim() ? doc.description : d.description,
      }),
    );
  }

  async function save() {
    if (readOnly) return;
    if (!slug) return setStatus({ kind: "error", message: c.needName });
    if (!doc.description.trim())
      return setStatus({ kind: "error", message: c.needWhen });
    setStatus({ kind: "saving" });
    try {
      const md = composeSkillMd({ ...doc, name: slug });
      if (isNew) {
        await createCustomSkill(slug, md, fromDraft ? "draft" : "manual");
      } else {
        await saveCustomSkill(
          slug,
          md,
          content?.version ?? 0,
          fromDraft ? "draft" : "manual",
        );
        setFromDraft(false);
      }
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
      setStatus({ kind: "saved" });
      if (isNew) onCreated(slug);
    } catch (e) {
      setStatus({
        kind: "error",
        message: c.saveFailed(e instanceof Error ? e.message : String(e)),
      });
    }
  }

  const header = (
    <>
      <h2 className="text-lg font-semibold" data-testid="studio-title">
        {isNew ? title.trim() || c.newSkillTitle : skillTitle(skill.name)}
      </h2>
      <p className="text-muted-foreground text-[13px]">
        {isNew
          ? c.usedBy([])
          : readOnly
            ? `${c.builtIn} · ${usedBy}`
            : skill.enabled
              ? usedBy
              : `${c.off} · ${usedBy}`}
      </p>
    </>
  );

  const footer = (
    <>
      {isCustom ? (
        <VersionHistory
          kind="skill"
          name={skill.name}
          onRestored={() =>
            void queryClient.invalidateQueries({ queryKey: ["skills"] })
          }
        />
      ) : null}
      {status.kind === "error" ? (
        <p
          className="text-destructive mr-auto text-sm"
          role="alert"
          data-testid="studio-save-error"
        >
          {status.message}
        </p>
      ) : status.kind === "saved" ? (
        <p className="text-muted-foreground mr-auto text-sm" role="status">
          {c.saved}
        </p>
      ) : null}
      <button
        type="button"
        className={outlineButton}
        disabled={readOnly}
        onClick={() => {
          setDoc(initial);
          setTitle("");
          setStatus({ kind: "idle" });
        }}
      >
        {c.cancel}
      </button>
      <button
        type="button"
        className={solidButton}
        disabled={readOnly || status.kind === "saving" || isLoading}
        onClick={() => void save()}
        data-testid="studio-save"
      >
        {status.kind === "saving" ? c.saving : c.save}
      </button>
    </>
  );

  return (
    <StudioTabs
      label={c.tabsLabel}
      tabs={[
        { id: "details", label: c.tabs.details },
        { id: "instructions", label: c.tabs.instructions },
        { id: "files", label: c.tabs.files },
        { id: "test", label: c.tabs.test },
      ]}
      value={tab}
      onChange={setTab}
      header={header}
      footer={footer}
    >
      <TabPanel
        value="details"
        className="flex flex-col gap-[18px] outline-none"
      >
        <label className="flex max-w-[480px] flex-col gap-1.5">
          <span className="text-[13px]">{c.name}</span>
          <input
            type="text"
            value={isNew ? title : skillTitle(skill.name)}
            readOnly={!isNew}
            onChange={(e) => setTitle(e.target.value)}
            className={fieldClass}
            data-testid="skill-name"
          />
          {isNew && slug ? (
            <span className="text-muted-foreground font-mono text-xs">
              {slug}
            </span>
          ) : null}
        </label>
        <div className="flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label htmlFor="skill-when" className="text-[13px]">
              {c.when}
            </label>
            {readOnly ? null : (
              <button
                type="button"
                className="border-border-strong text-foreground hover:bg-accent focus-visible:ring-ring inline-flex min-h-11 items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[13px] outline-none focus-visible:ring-2 disabled:opacity-50 md:min-h-0"
                onClick={() => void draftWhen()}
                disabled={drafting}
                data-testid="skill-when-draft"
              >
                <SparkleIcon className="text-primary size-3.5" aria-hidden />
                {drafting ? c.drafting : c.draft}
              </button>
            )}
          </div>
          <textarea
            id="skill-when"
            rows={3}
            value={doc.description}
            readOnly={readOnly}
            onChange={(e) => patch({ description: e.target.value })}
            className={cn(fieldClass, "resize-y rounded-xl")}
            data-testid="skill-when"
          />
          <span className="text-muted-foreground text-xs">{c.whenHelp}</span>
          <DraftNote note={draftNote} />
        </div>
      </TabPanel>
      <TabPanel
        value="instructions"
        className="flex flex-col gap-2.5 outline-none"
      >
        {readOnly ? null : (
          <DraftBar
            label={c.sentenceLabel}
            placeholder={c.sentencePlaceholder}
            draftLabel={c.draft}
            draftingLabel={c.drafting}
            needsSentence={c.draftNeedsSentence}
            onDraft={draftBody}
            testId="skill-draft-bar"
          />
        )}
        <InstructionsEditor
          body={doc.body}
          readOnly={readOnly}
          onChange={(body) => patch({ body })}
        />
        <DraftNote note={draftNote} />
      </TabPanel>
      <TabPanel value="files" className="flex flex-col gap-3 outline-none">
        <FilesTab name={isCustom ? skill.name : null} readOnly={readOnly} />
      </TabPanel>
      <TabPanel value="test" className="flex flex-col gap-2.5 outline-none">
        <p className="text-muted-foreground m-0">{c.testIntro}</p>
      </TabPanel>
    </StudioTabs>
  );
}

function InstructionsEditor({
  body,
  readOnly,
  onChange,
}: {
  body: string;
  readOnly: boolean;
  onChange: (body: string) => void;
}) {
  const c = useStudioCopy().skills;
  const ref = useRef<HTMLTextAreaElement>(null);
  const [preview, setPreview] = useState(readOnly);

  /** Wrap the selection (or insert at the caret) and keep the focus. */
  function wrap(before: string, after = before, linePrefix = false) {
    const el = ref.current;
    if (!el) return;
    const { selectionStart: s, selectionEnd: e } = el;
    const picked = body.slice(s, e);
    let next: string;
    if (linePrefix) {
      const lineStart = body.lastIndexOf("\n", s - 1) + 1;
      next = body.slice(0, lineStart) + before + body.slice(lineStart);
    } else {
      next = body.slice(0, s) + before + picked + after + body.slice(e);
    }
    onChange(next);
    requestAnimationFrame(() => {
      el.focus();
      const at = s + before.length;
      el.setSelectionRange(at, at + picked.length);
    });
  }

  const tool =
    "text-foreground-2 hover:bg-accent focus-visible:ring-ring min-h-11 rounded-md px-2 py-1 text-sm outline-none focus-visible:ring-2 disabled:opacity-50 md:min-h-0";
  return (
    <div className="border-border-strong overflow-hidden rounded-xl border">
      <div
        role="toolbar"
        aria-label={c.formatting}
        className="bg-card border-border flex flex-wrap gap-0.5 border-b px-2 py-1.5"
      >
        <button
          type="button"
          aria-label={c.bold}
          className={cn(tool, "font-bold")}
          disabled={readOnly || preview}
          onClick={() => wrap("**")}
        >
          B
        </button>
        <button
          type="button"
          aria-label={c.italic}
          className={cn(tool, "italic")}
          disabled={readOnly || preview}
          onClick={() => wrap("*")}
        >
          I
        </button>
        <button
          type="button"
          aria-label={c.heading}
          className={tool}
          disabled={readOnly || preview}
          onClick={() => wrap("## ", "", true)}
        >
          H
        </button>
        <button
          type="button"
          aria-label={c.list}
          className={tool}
          disabled={readOnly || preview}
          onClick={() => wrap("- ", "", true)}
        >
          {c.list}
        </button>
        <button
          type="button"
          aria-label={c.code}
          className={cn(tool, "font-mono")}
          disabled={readOnly || preview}
          onClick={() => wrap("`")}
        >
          {"</>"}
        </button>
        <span className="flex-1" />
        <button
          type="button"
          className={tool}
          aria-pressed={preview}
          onClick={() => setPreview((p) => !p)}
          disabled={readOnly}
          data-testid="skill-preview-toggle"
        >
          {preview ? c.edit : c.preview}
        </button>
      </div>
      {preview ? (
        <div
          className="bg-background flex min-h-[220px] flex-col gap-2 px-4 py-3.5 text-sm"
          data-testid="skill-body-preview"
        >
          {body.trim() ? (
            <MarkdownLite text={body} />
          ) : (
            <span className="text-muted-foreground">{c.noInstructions}</span>
          )}
        </div>
      ) : (
        <label className="block">
          <span className="sr-only">{c.instructionsLabel}</span>
          <textarea
            ref={ref}
            value={body}
            onChange={(e) => onChange(e.target.value)}
            className="bg-background text-foreground block min-h-[220px] w-full resize-y px-4 py-3.5 font-mono text-[13px] leading-[1.6] outline-none"
            data-testid="skill-body"
          />
        </label>
      )}
    </div>
  );
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function FilesTab({
  name,
  readOnly,
}: {
  name: string | null;
  readOnly: boolean;
}) {
  const c = useStudioCopy().skills;
  const queryClient = useQueryClient();
  const { files, error } = useSkillFiles(name);
  const input = useRef<HTMLInputElement>(null);
  const [note, setNote] = useState<{ text: string; bad: boolean } | null>(null);
  const [over, setOver] = useState(false);

  if (readOnly) {
    return <p className="text-muted-foreground">{c.filesBuiltIn}</p>;
  }
  if (!name) {
    return <p className="text-muted-foreground">{c.filesNew}</p>;
  }

  async function add(list: FileList | null) {
    for (const file of Array.from(list ?? [])) {
      setNote({ text: c.uploading(file.name), bad: false });
      try {
        await addSkillFile(name!, supportPathFor(file.name), await file.text());
        setNote(null);
      } catch (e) {
        setNote({
          text: c.uploadFailed(
            file.name,
            e instanceof Error ? e.message : String(e),
          ),
          bad: true,
        });
      }
    }
    void queryClient.invalidateQueries({ queryKey: ["skills", "files", name] });
  }

  return (
    <>
      {error ? (
        <p className="text-destructive text-sm" role="alert">
          {error.message}
        </p>
      ) : files?.length === 0 ? (
        <p className="text-muted-foreground text-sm">{c.noFiles}</p>
      ) : (
        (files ?? []).map((f) => (
          <div
            key={f.path}
            className="bg-card border-border flex items-center gap-3 rounded-lg border px-3.5 py-2.5"
            data-testid="skill-file"
          >
            <span className="min-w-0 flex-1 truncate font-mono text-[13px]">
              {f.path}
            </span>
            <span className="text-muted-foreground text-xs">
              {formatSize(f.size)}
            </span>
          </div>
        ))
      )}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          void add(e.dataTransfer.files);
        }}
        className={cn(
          "border-border-strong text-muted-foreground rounded-xl border border-dashed p-7 text-center",
          over && "bg-accent",
        )}
        data-testid="skill-drop"
      >
        {c.drop}{" "}
        <button
          type="button"
          onClick={() => input.current?.click()}
          className="text-primary underline underline-offset-2"
        >
          {c.choose}
        </button>
        <input
          ref={input}
          type="file"
          multiple
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(e) => {
            void add(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      {note ? (
        <p
          className={cn(
            "text-sm",
            note.bad ? "text-destructive" : "text-muted-foreground",
          )}
          role={note.bad ? "alert" : "status"}
        >
          {note.text}
        </p>
      ) : null}
    </>
  );
}
