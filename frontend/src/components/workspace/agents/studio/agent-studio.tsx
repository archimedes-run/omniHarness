"use client";

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
import { draft, skillSlug, useAgentRuns } from "@/core/studio";
import { cn } from "@/lib/utils";

import {
  InstructionsTab,
  OverviewTab,
  ScheduleTab,
  ToolsTab,
  AutonomyTab,
  type AgentForm,
} from "./agent-tabs";
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
  const [status, setStatus] = useState<
    | { kind: "idle" }
    | { kind: "saving" }
    | { kind: "saved" }
    | { kind: "error"; message: string }
  >({ kind: "idle" });
  const [draftNote, setDraftNote] = useState<{
    text: string;
    bad: boolean;
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
      patch({
        display_name: form.display_name.trim()
          ? form.display_name
          : d.display_name,
        description: form.description.trim() ? form.description : d.description,
        soul: d.instructions,
        tool_groups: d.tool_groups.length ? d.tool_groups : form.tool_groups,
        skills: d.skills.length ? d.skills : form.skills,
      });
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
    if (isLead) return;
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
        const created = await create.mutateAsync({ name: slug, ...fields });
        setStatus({ kind: "saved" });
        onCreated(created.name);
      } else {
        await update.mutateAsync({ name: id, request: fields });
        setStatus({ kind: "saved" });
      }
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
              <p className="text-muted-foreground mt-0.5 font-mono text-xs">
                {c.idNote(slug)}
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
      ) : dirty && !isLead ? (
        <p className="text-muted-foreground mr-auto text-sm">{c.unsaved}</p>
      ) : null}
      {mode === "new" ? (
        <Link
          href="/workspace/agents/new"
          className="text-primary mr-auto text-sm underline-offset-4 hover:underline"
        >
          {c.chatToBuild}
        </Link>
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
      {isLead ? null : (
        <button
          type="button"
          className={solidButton}
          onClick={() => void save()}
          disabled={status.kind === "saving"}
          data-testid="studio-save"
        >
          {status.kind === "saving" ? c.saving : c.save}
        </button>
      )}
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
      <AutonomyTab isLead={isLead} />
      <ScheduleTab isLead={isLead} agentId={mode === "new" ? null : id} />
    </StudioTabs>
  );
}
