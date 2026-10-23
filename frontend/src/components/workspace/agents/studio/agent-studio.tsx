"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  avatarClasses,
  LEAD_AGENT_ID,
  useAgents,
  useCreateAgent,
  useUpdateAgent,
  type Agent,
} from "@/core/agents";
import {
  draft,
  saveAutonomy,
  skillSlug,
  undoTo,
  useAgentRuns,
  useAutonomy,
  type AgentDraft,
} from "@/core/studio";
import { cn } from "@/lib/utils";

import {
  InstructionsTab,
  OverviewTab,
  ScheduleTab,
  ToolsTab,
  type AgentForm,
} from "./agent-tabs";
import { AutonomyTab } from "./autonomy";
import { useStudioCopy } from "./copy";
import { hasActiveSchedule } from "./runs";
import {
  RailItem,
  RailNew,
  StudioFrame,
  StudioTabs,
  outlineButton,
  solidButton,
} from "./studio-frame";
import { readItemParam, writeItemParam } from "./url-item";
import { VersionHistory } from "./version-history";

type Selection =
  | { kind: "lead" }
  | { kind: "agent"; name: string }
  | { kind: "new" };

export type AgentTab =
  | "overview"
  | "instructions"
  | "tools"
  | "autonomy"
  | "schedule";

/** "evening-wrap-up" -> "Evening wrap-up": the name until one is set. */
export function agentTitle(agent: Pick<Agent, "name" | "display_name">) {
  if (agent.display_name?.trim()) return agent.display_name.trim();
  const words = agent.name.replace(/[-_]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The board's initials: "Evening wrap-up" -> "EW", "Researcher" -> "Re". */
export function studioInitials(title: string) {
  const words = title.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) {
    const w = words[0]!;
    return w.charAt(0).toUpperCase() + w.charAt(1).toLowerCase();
  }
  return (
    words[0]!.charAt(0) + words[words.length - 1]!.charAt(0)
  ).toUpperCase();
}

export function AgentAvatar({
  id,
  name,
  size,
}: {
  id: string;
  name: string;
  size: "rail" | "header";
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full font-semibold",
        avatarClasses(id),
        size === "rail" ? "size-[26px] text-[10px]" : "size-10 text-[13px]",
      )}
    >
      {studioInitials(name)}
    </span>
  );
}

function selectionKey(s: Selection) {
  return s.kind === "agent" ? `agent:${s.name}` : s.kind;
}

/** The Agents capsule panel: Agent Studio (Agent-Studio.dc.html). */
export function AgentStudio() {
  const c = useStudioCopy().agents;
  const { agents, isLoading, error, disabled } = useAgents();
  const [selection, setSelection] = useState<Selection | null>(() => {
    const item = readItemParam();
    if (item === LEAD_AGENT_ID) return { kind: "lead" };
    if (item === "new") return { kind: "new" };
    return item ? { kind: "agent", name: item } : null;
  });

  // Until the user picks, the first custom agent (or the lead agent).
  const current: Selection =
    selection ??
    (agents[0] ? { kind: "agent", name: agents[0].name } : { kind: "lead" });

  useEffect(() => {
    if (selection) {
      writeItemParam(
        selection.kind === "agent"
          ? selection.name
          : selection.kind === "lead"
            ? LEAD_AGENT_ID
            : "new",
      );
    }
  }, [selection]);
  useEffect(() => () => writeItemParam(null), []);

  const selectedAgent =
    current.kind === "agent"
      ? (agents.find((a) => a.name === current.name) ?? null)
      : null;

  const rail = (
    <>
      <RailNew
        label={c.newAgent}
        selected={current.kind === "new"}
        onClick={() => setSelection({ kind: "new" })}
      />
      <RailItem
        selected={current.kind === "lead"}
        onClick={() => setSelection({ kind: "lead" })}
        avatar={<AgentAvatar id={LEAD_AGENT_ID} name="L" size="rail" />}
        testId="studio-item-lead"
      >
        {c.leadName}
      </RailItem>
      {agents.map((agent) => (
        <RailItem
          key={agent.name}
          selected={current.kind === "agent" && current.name === agent.name}
          onClick={() => setSelection({ kind: "agent", name: agent.name })}
          avatar={
            <AgentAvatar id={agent.name} name={agentTitle(agent)} size="rail" />
          }
          testId={`studio-item-${agent.name}`}
        >
          {agentTitle(agent)}
        </RailItem>
      ))}
    </>
  );

  let body;
  if (isLoading) {
    body = <p className="text-muted-foreground p-7 text-sm">{c.loading}</p>;
  } else if (disabled && current.kind !== "lead") {
    body = (
      <div className="p-7 text-sm" data-testid="agents-disabled">
        <p className="text-foreground font-medium">{c.disabledTitle}</p>
        <p className="text-muted-foreground mt-1">{c.disabledBody}</p>
      </div>
    );
  } else if (error && !disabled && current.kind !== "lead") {
    body = (
      <p className="text-destructive p-7 text-sm" role="alert">
        {c.loadFailed(error.message)}
      </p>
    );
  } else if (current.kind === "agent" && !selectedAgent) {
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
      <AgentEditor
        key={selectionKey(current)}
        mode={current.kind}
        agent={selectedAgent}
        onCreated={(name) => setSelection({ kind: "agent", name })}
      />
    );
  }

  return (
    <StudioFrame rail={rail} railLabel={c.railLabel} testId="agent-studio">
      {body}
    </StudioFrame>
  );
}

function formFrom(agent: Agent | null): AgentForm {
  return {
    display_name: agent ? agentTitle(agent) : "",
    description: agent?.description ?? "",
    soul: agent?.soul ?? "",
    tool_groups: agent ? agent.tool_groups : null,
    skills: agent ? agent.skills : null,
    projects: agent?.projects ?? [],
  };
}

function AgentEditor({
  mode,
  agent,
  onCreated,
}: {
  mode: "lead" | "agent" | "new";
  agent: Agent | null;
  onCreated: (name: string) => void;
}) {
  const c = useStudioCopy().agents;
  const [tab, setTab] = useState<AgentTab>(
    mode === "new" ? "instructions" : "overview",
  );
  const initial = useMemo(() => formFrom(agent), [agent]);
  const [form, setForm] = useState<AgentForm>(initial);
  // A new version from the server (a save, a restore) becomes the form.
  useEffect(() => setForm(initial), [initial]);
  const [fromDraft, setFromDraft] = useState(false);
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<
    | { kind: "idle" }
    | { kind: "saving" }
    | { kind: "saved"; version: number | null; undoTo: number | null }
    | { kind: "undone"; version: number }
    | { kind: "error"; message: string }
  >({ kind: "idle" });

  /** Restore the version the last save was made from, as a new version. */
  async function undoSave(to: number, base: number) {
    try {
      await undoTo("agent", id, to, base);
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["studio"] });
      setStatus({ kind: "undone", version: to });
    } catch (e) {
      const stale = (e as { status?: number }).status === 409;
      setStatus({
        kind: "error",
        message: stale
          ? c.undoStale
          : c.undoFailed(e instanceof Error ? e.message : String(e)),
      });
    }
  }
  const [draftNote, setDraftNote] = useState<{
    text: string;
    bad: boolean;
  } | null>(null);
  /** What the last draft suggested for the tabs a draft must not decide on
   * the user's behalf: autonomy (never ticked for them) and a schedule
   * (never created). Shown on those tabs for review. */
  const [suggested, setSuggested] = useState<{
    autonomy: string[];
    schedule: AgentDraft["schedule"];
  } | null>(null);
  const create = useCreateAgent();
  const { runs } = useAgentRuns(
    mode === "new" ? null : (agent?.name ?? LEAD_AGENT_ID),
  );
  const update = useUpdateAgent();

  const isLead = mode === "lead";
  const id = isLead ? LEAD_AGENT_ID : (agent?.name ?? "new");
  const slug = mode === "new" ? skillSlug(form.display_name) : id;
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);
  // A new agent has no grants yet; the lead agent's view lists the classes
  // the rules in force let you grant, so they can be chosen before it exists.
  const { autonomy, error: autonomyError } = useAutonomy(
    mode === "new" ? LEAD_AGENT_ID : id,
  );
  const savedGrants =
    mode === "new"
      ? []
      : (autonomy?.classes ?? [])
          .filter((cls) => cls.granted)
          .map((cls) => cls.id);
  // null: untouched, so the saved grants show.
  const [granted, setGranted] = useState<string[] | null>(null);
  const effectiveGrants = granted ?? savedGrants;
  const grantsDirty =
    granted !== null &&
    [...granted].sort().join() !== [...savedGrants].sort().join();
  const grantLabels = (autonomy?.classes ?? [])
    .filter((cls) => effectiveGrants.includes(cls.id))
    .map((cls) => cls.label);

  const patch = (next: Partial<AgentForm>) => {
    setForm((f) => ({ ...f, ...next }));
    setStatus({ kind: "idle" });
  };

  /** Fill the large fields from one sentence, for review. Saves nothing. */
  async function onDraft(sentence: string) {
    try {
      const result = await draft("agent", {
        sentence,
        agent_name: mode === "agent" ? id : null,
      });
      const d = result.agent!;
      // One sentence fills every tab: the text fields and the projects,
      // tools and skills go into the form for review; grants and a schedule
      // are shown as suggestions on their tabs.
      patch({
        display_name: form.display_name.trim()
          ? form.display_name
          : d.display_name,
        description: form.description.trim() ? form.description : d.description,
        soul: d.instructions,
        tool_groups: d.tool_groups.length ? d.tool_groups : form.tool_groups,
        skills: d.skills.length ? d.skills : form.skills,
        projects: d.projects?.length ? d.projects : form.projects,
      });
      setSuggested({
        autonomy: d.autonomy ?? [],
        schedule: d.schedule ?? null,
      });
      setFromDraft(true);
      setDraftNote({
        text:
          c.draftReady(result.model) +
          (result.dropped.length ? ` ${c.draftDropped(result.dropped)}` : ""),
        bad: false,
      });
    } catch (e) {
      setDraftNote({
        text: c.draftFailed(e instanceof Error ? e.message : String(e)),
        bad: true,
      });
    }
  }

  async function save() {
    if (mode === "new" && !slug) {
      setStatus({ kind: "error", message: c.needName });
      return;
    }
    setStatus({ kind: "saving" });
    try {
      const fields = {
        display_name: form.display_name.trim() || null,
        description: form.description,
        soul: form.soul,
        tool_groups: form.tool_groups,
        skills: form.skills,
        projects: form.projects,
      };
      if (mode === "new") {
        const created = await create.mutateAsync({
          name: slug,
          ...fields,
          source: fromDraft ? "draft" : "manual",
        });
        // What the user ticked on Autonomy (never a draft's suggestion by
        // itself), as the agent's next version.
        if (effectiveGrants.length > 0) {
          await saveAutonomy(
            created.name,
            effectiveGrants,
            created.version ?? 1,
          );
        }
        void queryClient.invalidateQueries({ queryKey: ["agents"] });
        void queryClient.invalidateQueries({ queryKey: ["studio"] });
        setStatus({ kind: "saved", version: null, undoTo: null });
        onCreated(created.name);
        return;
      }
      // Each write names the version it was made from; the store refuses a
      // stale one. An agent edit makes a new version, so the grants that
      // follow it are based on that one.
      let version = autonomy?.version ?? agent?.version ?? 0;
      const before = agent?.version ?? 0;
      let edited = false;
      if (!isLead && dirty) {
        const saved = await update.mutateAsync({
          name: id,
          request: {
            ...fields,
            base_version: agent?.version ?? 0,
            source: fromDraft ? "draft" : "manual",
          },
        });
        version = saved.version ?? version;
        edited = true;
        setFromDraft(false);
      }
      if (grantsDirty) {
        const view = await saveAutonomy(id, effectiveGrants, version);
        version = view.version ?? version;
        setGranted(null);
      }
      void queryClient.invalidateQueries({ queryKey: ["studio"] });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      // Undo brings back the version this edit was made from (its content;
      // grants are only ever changed on the Autonomy tab).
      setStatus({
        kind: "saved",
        version: isLead ? null : version,
        undoTo: edited && before > 0 ? before : null,
      });
    } catch (e) {
      setStatus({
        kind: "error",
        message: c.saveFailed(e instanceof Error ? e.message : String(e)),
      });
    }
  }

  const title = isLead ? c.leadName : form.display_name;
  const header = (
    <div className="flex flex-wrap items-center gap-3">
      <AgentAvatar
        id={id}
        name={isLead ? "L" : title || c.newAgentTitle}
        size="header"
      />
      <div className="min-w-0 flex-[1_1_260px]">
        {isLead ? (
          <>
            <h2 className="text-lg font-semibold" data-testid="studio-title">
              {c.leadName}
            </h2>
            <p className="text-muted-foreground text-[13px]">
              {c.leadSubtitle}
            </p>
          </>
        ) : (
          <>
            <input
              aria-label={c.nameLabel}
              data-testid="studio-title"
              value={form.display_name}
              placeholder={c.namePlaceholder}
              onChange={(e) => patch({ display_name: e.target.value })}
              className="placeholder:text-muted-foreground hover:border-border focus-visible:border-ring -mx-1.5 block w-full rounded-md border border-transparent bg-transparent px-1.5 text-lg font-semibold outline-none"
            />
            <input
              aria-label={c.descriptionLabel}
              value={form.description}
              placeholder={c.descriptionPlaceholder}
              onChange={(e) => patch({ description: e.target.value })}
              className="text-muted-foreground placeholder:text-muted-foreground hover:border-border focus-visible:border-ring -mx-1.5 block w-full rounded-md border border-transparent bg-transparent px-1.5 text-[13px] outline-none"
            />
            {mode === "new" && slug ? (
              <p
                className="text-muted-foreground mt-0.5 font-mono text-xs"
                data-testid="studio-id-note"
              >
                {status.kind === "saved"
                  ? c.idNote(slug)
                  : c.idNoteUnsaved(slug)}
              </p>
            ) : null}
          </>
        )}
      </div>
      {hasActiveSchedule(runs) ? (
        <span
          className="text-success border-success/60 rounded-md border px-2 py-0.5 text-xs"
          data-testid="studio-active"
        >
          {c.active}
        </span>
      ) : null}
    </div>
  );

  const footer = (
    <>
      {mode === "new" ? null : (
        <VersionHistory
          kind="agent"
          name={id}
          onRestored={() => {
            void queryClient.invalidateQueries({ queryKey: ["agents"] });
            void queryClient.invalidateQueries({ queryKey: ["studio"] });
          }}
        />
      )}
      {status.kind === "error" ? (
        <p
          className="text-destructive mr-auto text-sm"
          role="alert"
          data-testid="studio-save-error"
        >
          {status.message}
        </p>
      ) : status.kind === "saved" ? (
        <p
          className="text-muted-foreground mr-auto flex flex-wrap items-center gap-2 text-sm"
          role="status"
          data-testid="studio-saved"
        >
          {status.version ? c.savedVersion(status.version) : c.saved}
          {status.undoTo && status.version ? (
            <button
              type="button"
              className="text-primary min-h-11 underline-offset-2 hover:underline md:min-h-0"
              onClick={() => void undoSave(status.undoTo!, status.version!)}
              data-testid="studio-undo"
            >
              {c.undo}
            </button>
          ) : null}
        </p>
      ) : status.kind === "undone" ? (
        <p
          className="text-muted-foreground mr-auto text-sm"
          role="status"
          data-testid="studio-undone"
        >
          {c.undone(status.version)}
        </p>
      ) : (dirty && !isLead) || grantsDirty ? (
        <p className="text-muted-foreground mr-auto text-sm">{c.unsaved}</p>
      ) : null}
      {mode === "new" ? (
        <button
          type="button"
          className={outlineButton}
          disabled
          title={c.testRunAfterSave}
          data-testid="studio-test-run"
        >
          {c.testRun}
        </button>
      ) : (
        <Link
          href={
            isLead
              ? "/workspace/chats/new"
              : `/workspace/agents/${encodeURIComponent(id)}/chats/new`
          }
          className={outlineButton}
          data-testid="studio-test-run"
        >
          {c.testRun}
        </Link>
      )}
      {
        <button
          type="button"
          className={solidButton}
          onClick={() => void save()}
          disabled={status.kind === "saving"}
          data-testid="studio-save"
        >
          {status.kind === "saving" ? c.saving : c.save}
        </button>
      }
    </>
  );

  const tabs: { id: AgentTab; label: string }[] = [
    { id: "overview", label: c.tabs.overview },
    { id: "instructions", label: c.tabs.instructions },
    { id: "tools", label: c.tabs.tools },
    { id: "autonomy", label: c.tabs.autonomy },
    { id: "schedule", label: c.tabs.schedule },
  ];

  return (
    <StudioTabs
      label={c.tabsLabel}
      tabs={tabs}
      value={tab}
      onChange={setTab}
      header={header}
      footer={footer}
    >
      <OverviewTab
        form={form}
        patch={patch}
        isLead={isLead}
        agentId={mode === "new" ? null : id}
        grantLabels={autonomy ? grantLabels : null}
        suggestedSchedule={suggested?.schedule ?? null}
      />
      <InstructionsTab
        form={form}
        patch={patch}
        isLead={isLead}
        onDraft={onDraft}
        draftNote={draftNote}
      />
      <ToolsTab
        form={form}
        patch={patch}
        isLead={isLead}
        draftNote={draftNote}
      />
      <AutonomyTab
        agentId={mode === "new" ? null : id}
        isNew={mode === "new"}
        suggested={suggested?.autonomy ?? []}
        autonomy={autonomy}
        error={autonomyError}
        granted={effectiveGrants}
        onChange={(next) => {
          setGranted(next);
          setStatus({ kind: "idle" });
        }}
      />
      <ScheduleTab
        isLead={isLead}
        agentId={mode === "new" ? null : id}
        suggested={suggested?.schedule ?? null}
      />
    </StudioTabs>
  );
}
