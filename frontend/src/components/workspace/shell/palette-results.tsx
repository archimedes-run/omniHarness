"use client";

import { useQueries } from "@tanstack/react-query";
import {
  BotIcon,
  FolderKanbanIcon,
  ListChecksIcon,
  MessagesSquareIcon,
  SparklesIcon,
  ZapIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { CommandGroup, CommandItem } from "@/components/ui/command";
import { useAgents } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { loadProject } from "@/core/ledger/api";
import { useProjects } from "@/core/ledger/hooks";
import { useSkills } from "@/core/skills/hooks";
import { useThreads } from "@/core/threads/queries";
import { pathOfThread, titleOfThread } from "@/core/threads/utils";
import { useTriggerRules } from "@/core/triggers/hooks";

const PER_GROUP = 5;
// Tasks have no cross-project search route yet: each project is read, up to
// this many, and only while there is a query.
const TASK_PROJECTS = 20;

/** Case-insensitive: every word of the query appears in one of the texts. */
export function matches(
  query: string,
  ...texts: (string | null | undefined)[]
) {
  const words = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = texts.filter(Boolean).join(" ").toLowerCase();
  return words.every((w) => haystack.includes(w));
}

interface Hit {
  key: string;
  label: string;
  detail?: string | null;
  href: string;
}

function Group({
  heading,
  icon: Icon,
  hits,
  error,
  loading,
  source,
  onGo,
}: {
  heading: string;
  icon: typeof BotIcon;
  hits: Hit[];
  error?: unknown;
  loading?: boolean;
  source: string;
  onGo: (href: string) => void;
}) {
  const { t } = useI18n();
  let status: ReactNode = null;
  // A source that cannot be searched says so: no hits from it is not "none".
  if (error != null) {
    status = (
      <p
        className="text-destructive px-2 py-1.5 text-xs"
        role="status"
        data-testid="palette-unsearchable"
        data-source={source}
      >
        {t.shell.cannotSearch(
          heading,
          error instanceof Error ? error.message : JSON.stringify(error),
        )}
      </p>
    );
  } else if (loading && hits.length === 0) {
    status = (
      <p className="text-muted-foreground px-2 py-1.5 text-xs" role="status">
        {t.shell.searching}
      </p>
    );
  }
  if (hits.length === 0 && !status) return null;
  return (
    <CommandGroup heading={heading} data-testid={`palette-group-${source}`}>
      {status}
      {hits.slice(0, PER_GROUP).map((hit) => (
        <CommandItem
          key={hit.key}
          value={hit.key}
          onSelect={() => onGo(hit.href)}
          data-testid="palette-hit"
          data-source={source}
        >
          <Icon />
          <span className="truncate">{hit.label}</span>
          {hit.detail && (
            <span className="text-muted-foreground ml-auto truncate text-xs">
              {hit.detail}
            </span>
          )}
        </CommandItem>
      ))}
    </CommandGroup>
  );
}

/** Search results, mounted only while the palette is open with a query, so
 * no page reads these sources until someone searches. */
export function PaletteResults({
  query,
  onGo,
}: {
  query: string;
  onGo: (href: string) => void;
}) {
  const { t } = useI18n();
  const threads = useThreads();
  const {
    projects,
    error: projectsError,
    isLoading: projectsLoading,
  } = useProjects();
  const {
    agents,
    error: agentsError,
    disabled,
    isLoading: agentsLoading,
  } = useAgents();
  const { skills, error: skillsError, isLoading: skillsLoading } = useSkills();
  const {
    view: rules,
    error: rulesError,
    isLoading: rulesLoading,
  } = useTriggerRules();

  const projectViews = useQueries({
    queries: (projects ?? []).slice(0, TASK_PROJECTS).map((p) => ({
      queryKey: ["ledger", "project", p.id],
      queryFn: () => loadProject(p.id),
    })),
  });

  const chatHits: Hit[] = (threads.data ?? [])
    .filter((thread) => matches(query, titleOfThread(thread)))
    .map((thread) => ({
      key: `chat:${thread.thread_id}`,
      label: titleOfThread(thread),
      href: pathOfThread(thread),
    }));

  const projectHits: Hit[] = (projects ?? [])
    .filter((p) => matches(query, p.name, p.why))
    .map((p) => ({
      key: `project:${p.id}`,
      label: p.name,
      detail: p.status === "active" ? null : p.status,
      href: `/workspace/projects/${p.id}`,
    }));

  const taskHits: Hit[] = projectViews.flatMap((q) =>
    (q.data?.tasks ?? [])
      .filter((task) => matches(query, task.title, task.short_id))
      .map((task) => ({
        key: `task:${task.id}`,
        label: task.title,
        detail: q.data?.project.name,
        href: `/workspace/projects/${task.project_id}`,
      })),
  );
  const taskError = projectViews.find((q) => q.error)?.error ?? projectsError;

  const agentHits: Hit[] = disabled
    ? []
    : agents
        .filter((a) => matches(query, a.name, a.description))
        .map((a) => ({
          key: `agent:${a.name}`,
          label: a.name,
          detail: a.description,
          href: `/workspace/agents/${encodeURIComponent(a.name)}/chats/new`,
        }));

  const skillHits: Hit[] = skills
    .filter((s) => matches(query, s.name, s.description))
    .map((s) => ({
      key: `skill:${s.name}`,
      label: s.name,
      detail: s.enabled ? null : "off",
      href: "/workspace/settings/skills",
    }));

  const ruleHits: Hit[] = (rules?.rules ?? [])
    .filter((r) => matches(query, r.id, r.prompt))
    .map((r) => ({
      key: `automation:${r.id}`,
      label: r.id,
      detail: r.enabled ? null : "off",
      href: `/workspace/automations/${encodeURIComponent(r.id)}`,
    }));

  return (
    <>
      <Group
        heading={t.shell.groupChats}
        icon={MessagesSquareIcon}
        hits={chatHits}
        error={threads.error}
        loading={threads.isLoading}
        source="chats"
        onGo={onGo}
      />
      <Group
        heading={t.shell.groupProjects}
        icon={FolderKanbanIcon}
        hits={projectHits}
        error={projectsError}
        loading={projectsLoading}
        source="projects"
        onGo={onGo}
      />
      <Group
        heading={t.shell.groupTasks}
        icon={ListChecksIcon}
        hits={taskHits}
        error={taskError}
        loading={projectsLoading || projectViews.some((q) => q.isLoading)}
        source="tasks"
        onGo={onGo}
      />
      <Group
        heading={t.shell.groupAgents}
        icon={BotIcon}
        hits={agentHits}
        error={disabled ? null : agentsError}
        loading={agentsLoading}
        source="agents"
        onGo={onGo}
      />
      <Group
        heading={t.shell.groupSkills}
        icon={SparklesIcon}
        hits={skillHits}
        error={skillsError}
        loading={skillsLoading}
        source="skills"
        onGo={onGo}
      />
      <Group
        heading={t.shell.groupAutomations}
        icon={ZapIcon}
        hits={ruleHits}
        error={rulesError}
        loading={rulesLoading}
        source="automations"
        onGo={onGo}
      />
    </>
  );
}
