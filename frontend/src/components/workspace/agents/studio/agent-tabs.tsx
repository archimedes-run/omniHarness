"use client";

import { XIcon } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useShell } from "@/components/workspace/shell/shell-context";
import { useProjects } from "@/core/ledger/hooks";
import { useSkills } from "@/core/skills/hooks";
import { useAgentRuns, useStudioOptions } from "@/core/studio";

import { useStudioCopy } from "./copy";
import { nextRunText, RecentRuns, ScheduleList } from "./runs";
import {
  TabPanel,
  chipClass,
  dashedChip,
  outlineButton,
  statCard,
} from "./studio-frame";

export interface AgentForm {
  display_name: string;
  description: string;
  soul: string;
  /** null: no limit (every tool). */
  tool_groups: string[] | null;
  /** null: every enabled skill. */
  skills: string[] | null;
  projects: string[];
}

interface TabProps {
  form: AgentForm;
  patch: (next: Partial<AgentForm>) => void;
  isLead: boolean;
}

interface OverviewProps extends TabProps {
  /** null for an agent not saved yet. */
  agentId: string | null;
}

export function usesSummary(
  form: Pick<AgentForm, "tool_groups" | "skills">,
  c: ReturnType<typeof useStudioCopy>["agents"],
): string {
  const tools =
    form.tool_groups === null
      ? c.allTools
      : form.tool_groups.length === 0
        ? c.noTools
        : form.tool_groups.join(", ");
  const skills =
    form.skills === null
      ? c.allSkills
      : form.skills.length === 0
        ? c.noSkills
        : c.skillCount(form.skills.length);
  return `${tools} · ${skills}`;
}

export function OverviewTab({ form, patch, isLead, agentId }: OverviewProps) {
  const c = useStudioCopy().agents;
  const { projects, error: projectsError } = useProjects();
  const { runs, error: runsError } = useAgentRuns(agentId);
  const names = form.projects.map(
    (id) => projects?.find((p) => p.id === id)?.name ?? c.goneProject,
  );

  return (
    <TabPanel
      value="overview"
      className="flex flex-col gap-[18px] outline-none"
    >
      <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3">
        <div className={statCard} data-testid="overview-works-on">
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground text-xs">{c.worksOn}</span>
            {isLead ? null : (
              <DropdownMenu>
                <DropdownMenuTrigger
                  className="text-primary focus-visible:ring-ring -my-1 min-h-11 rounded-md px-1.5 py-0.5 text-xs outline-none hover:underline focus-visible:ring-2 md:min-h-0"
                  data-testid="choose-projects"
                >
                  {c.chooseProjects}
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="max-h-72 w-64">
                  {(projects ?? []).length === 0 ? (
                    <DropdownMenuItem disabled>{c.noProjects}</DropdownMenuItem>
                  ) : (
                    (projects ?? []).map((p) => (
                      <DropdownMenuCheckboxItem
                        key={p.id}
                        checked={form.projects.includes(p.id)}
                        onSelect={(e) => e.preventDefault()}
                        onCheckedChange={(on) =>
                          patch({
                            projects: on
                              ? [...form.projects, p.id]
                              : form.projects.filter((x) => x !== p.id),
                          })
                        }
                      >
                        {p.name}
                      </DropdownMenuCheckboxItem>
                    ))
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
          <div className="mt-1">
            {projectsError && form.projects.length > 0
              ? c.projectsUnreadable
              : names.length > 0
                ? names.join(", ")
                : c.noProjects}
          </div>
        </div>
        <div className={statCard} data-testid="overview-uses">
          <div className="text-muted-foreground text-xs">{c.uses}</div>
          <div className="mt-1">
            {isLead ? `${c.allTools} · ${c.allSkills}` : usesSummary(form, c)}
          </div>
        </div>
        <div className={statCard} data-testid="overview-next-run">
          <div className="text-muted-foreground text-xs">{c.nextRun}</div>
          <div className="mt-1">
            {agentId ? nextRunText(runs, runsError, c) : c.notSetUp}
          </div>
        </div>
        <div className={statCard} data-testid="overview-on-its-own">
          <div className="text-muted-foreground text-xs">{c.mayOnItsOwn}</div>
          <div className="mt-1">{c.nothingOnItsOwn}</div>
        </div>
      </div>
      {agentId ? <RecentRuns agentId={agentId} /> : null}
    </TabPanel>
  );
}

export function InstructionsTab({ form, patch, isLead }: TabProps) {
  const c = useStudioCopy().agents;
  if (isLead) {
    return (
      <TabPanel value="instructions" className="outline-none">
        <p className="text-foreground-2">{c.leadInstructions}</p>
      </TabPanel>
    );
  }
  return (
    <TabPanel
      value="instructions"
      className="flex flex-col gap-2.5 outline-none"
    >
      <label className="block">
        <span className="sr-only">{c.instructionsLabel}</span>
        <textarea
          rows={9}
          value={form.soul}
          onChange={(e) => patch({ soul: e.target.value })}
          data-testid="agent-instructions"
          className="bg-card border-border-strong text-foreground focus-visible:ring-ring box-border w-full resize-y rounded-xl border px-3.5 py-3 text-sm leading-[1.6] outline-none focus-visible:ring-2"
        />
      </label>
      <p className="text-muted-foreground text-xs">{c.editFreely}</p>
    </TabPanel>
  );
}

function Chips({
  values,
  all,
  allLabel,
  options,
  offNote,
  onChange,
  testId,
}: {
  values: string[] | null;
  all: string;
  allLabel: string;
  options: { name: string; off?: boolean }[];
  offNote: string;
  onChange: (next: string[] | null) => void;
  testId: string;
}) {
  const c = useStudioCopy().agents;
  const rest = options.filter((o) => !(values ?? []).includes(o.name));
  return (
    <div className="flex flex-wrap gap-2" data-testid={testId}>
      {values === null ? (
        <span className={chipClass}>{all}</span>
      ) : (
        values.map((name) => (
          <span key={name} className={chipClass}>
            {name}
            <button
              type="button"
              aria-label={c.remove(name)}
              onClick={() => onChange(values.filter((v) => v !== name))}
              className="text-muted-foreground hover:text-foreground focus-visible:ring-ring -mr-1 rounded p-0.5 outline-none focus-visible:ring-2"
            >
              <XIcon className="size-3.5" aria-hidden />
            </button>
          </span>
        ))
      )}
      <DropdownMenu>
        <DropdownMenuTrigger className={dashedChip}>
          {c.add}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="max-h-72 w-64">
          {values === null ? null : (
            <>
              <DropdownMenuItem onSelect={() => onChange(null)}>
                {allLabel}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          )}
          {rest.map((o) => (
            <DropdownMenuItem
              key={o.name}
              onSelect={() => onChange([...(values ?? []), o.name])}
            >
              {o.name}
              {o.off ? (
                <span className="text-muted-foreground ml-auto text-xs">
                  {offNote}
                </span>
              ) : null}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export function ToolsTab({ form, patch, isLead }: TabProps) {
  const c = useStudioCopy().agents;
  const { options } = useStudioOptions();
  const { skills } = useSkills();
  if (isLead) {
    return (
      <TabPanel value="tools" className="outline-none">
        <p className="text-foreground-2">{c.leadTools}</p>
      </TabPanel>
    );
  }
  return (
    <TabPanel value="tools" className="flex flex-col gap-4 outline-none">
      <div className="text-muted-foreground text-xs">{c.toolGroups}</div>
      <Chips
        values={form.tool_groups}
        all={c.allTools}
        allLabel={c.allToolGroups}
        options={(options?.tool_groups ?? []).map((name) => ({ name }))}
        offNote=""
        onChange={(tool_groups) => patch({ tool_groups })}
        testId="agent-tool-groups"
      />
      <div className="text-muted-foreground text-xs">{c.skillsEveryRun}</div>
      <Chips
        values={form.skills}
        all={c.allSkills}
        allLabel={c.allEnabledSkills}
        options={skills.map((s) => ({ name: s.name, off: !s.enabled }))}
        offNote={c.skillOff}
        onChange={(next) => patch({ skills: next })}
        testId="agent-skills"
      />
    </TabPanel>
  );
}

export function AutonomyTab({ isLead: _isLead }: { isLead: boolean }) {
  const c = useStudioCopy().agents;
  return (
    <TabPanel value="autonomy" className="flex flex-col gap-3.5 outline-none">
      <p className="text-foreground-2 m-0">{c.autonomyIntro}</p>
    </TabPanel>
  );
}

export function ScheduleTab({
  isLead,
  agentId,
}: {
  isLead: boolean;
  agentId: string | null;
}) {
  const c = useStudioCopy().agents;
  const { openPanel } = useShell();
  return (
    <TabPanel value="schedule" className="flex flex-col gap-3.5 outline-none">
      <div className="bg-card border-border-strong flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3">
        <div className="flex-[1_1_260px]">
          {isLead ? (
            <p className="text-foreground-2 mb-2">{c.scheduleLead}</p>
          ) : null}
          {agentId ? (
            <ScheduleList agentId={agentId} />
          ) : (
            <>
              <p className="font-medium">{c.scheduleNone}</p>
              <p className="text-muted-foreground mt-0.5 text-sm">
                {c.notSetUpWhy}
              </p>
            </>
          )}
        </div>
        <button
          type="button"
          className={outlineButton}
          onClick={() => openPanel("automations")}
        >
          {c.openAutomations}
        </button>
      </div>
    </TabPanel>
  );
}
