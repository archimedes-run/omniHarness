"use client";

import {
  BotIcon,
  ClockIcon,
  MessageSquareIcon,
  PlusIcon,
  SearchIcon,
  SparklesIcon,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";

import {
  LEAD_AGENT_ID,
  LEAD_AVATAR,
  avatarIdFor,
  useAgents,
  type Agent,
} from "@/core/agents";
import {
  STATUS_ORDER,
  agentStatus,
  nextRunLine,
  useAgentRuns,
  useAgentsRuns,
  useToolCatalog,
  type AgentStatus,
  type CatalogIntegration,
} from "@/core/studio";

import { useStudioCopy } from "./copy";
import { Av, Kbd, Mono, StatusPill } from "./parts";
import { ListHead, useStudio } from "./studio";

/** "evening-wrap-up" -> "Evening wrap-up": the name until one is set. */
export function agentTitle(agent: Pick<Agent, "name" | "display_name">) {
  if (agent.display_name?.trim()) return agent.display_name.trim();
  const words = agent.name.replace(/[-_]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

type Filter = "all" | AgentStatus;

/** The Agents list (design: 02 agents list). */
export function AgentsList() {
  const c = useStudioCopy();
  const studio = useStudio();
  const { agents, isLoading, error, disabled } = useAgents();
  const runs = useAgentsRuns(agents.map((a) => a.name));
  const { catalog } = useToolCatalog(agents.length > 0);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const search = useRef<HTMLInputElement>(null);

  const rows = useMemo(
    () =>
      agents.map((agent, i) => {
        const r = runs[i]?.data;
        const status = agentStatus(agent.soul, r);
        return { agent, runs: r, status };
      }),
    [agents, runs],
  );
  const counts = useMemo(() => {
    const out: Record<string, number> = { all: rows.length };
    for (const row of rows)
      if (row.status) out[row.status] = (out[row.status] ?? 0) + 1;
    return out;
  }, [rows]);
  const filters: Filter[] = [
    "all",
    ...STATUS_ORDER.filter((s) => s !== "paused" || (counts.paused ?? 0) > 0),
  ];
  const needle = q.trim().toLowerCase();
  const shown = rows.filter(
    (row) =>
      (filter === "all" || row.status === filter) &&
      (!needle ||
        `${agentTitle(row.agent)} ${row.agent.description} ${row.agent.name}`
          .toLowerCase()
          .includes(needle)),
  );
  const running = rows.filter(
    (r) => r.status === "active" || r.status === "scheduled",
  ).length;

  const onKeyDown = (e: React.KeyboardEvent) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(
      (e.target as HTMLElement).tagName,
    );
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "/") {
      e.preventDefault();
      search.current?.focus();
    } else if (e.key === "n" || e.key === "N") {
      e.preventDefault();
      studio.go({ view: "agent", id: null });
    }
  };

  let content;
  if (isLoading) content = <p className="help">{c.agents.loading}</p>;
  else if (disabled)
    content = (
      <p className="help" data-testid="agents-disabled">
        {c.agents.disabled}
      </p>
    );
  else if (error)
    content = (
      <p className="err" role="alert">
        {c.agents.loadFailed(error.message)}
      </p>
    );
  else if (shown.length === 0 && (needle || filter !== "all"))
    content = (
      <div className="empty-search">
        {c.agents.noMatch(q)}{" "}
        <button
          type="button"
          className="link"
          onClick={() => {
            setQ("");
            setFilter("all");
          }}
        >
          {c.agents.clear}
        </button>
      </div>
    );
  else
    content = (
      <div className="cards" data-testid="agent-cards">
        {filter === "all" && !needle ? <LeadCard /> : null}
        {shown.map((row) => (
          <AgentCard
            key={row.agent.name}
            agent={row.agent}
            status={row.status}
            runs={row.runs}
            integrations={catalog?.integrations}
          />
        ))}
        <button
          type="button"
          className="acard new"
          onClick={() => studio.go({ view: "agent", id: null })}
          data-testid="agent-describe-new"
        >
          <SparklesIcon size={22} aria-hidden />
          <b style={{ fontWeight: 600 }}>{c.agents.describeTitle}</b>
          <span className="help">{c.agents.describeBody}</span>
        </button>
      </div>
    );

  return (
    <div className="contents" onKeyDown={onKeyDown}>
      <ListHead
        which="agents"
        title={c.agents.title}
        subtitle={c.agents.subtitle}
        icon={<BotIcon size={18} />}
      />
      <div className="m-body" data-testid="agents-list">
        <div className="toolbar">
          <label className="with-ico">
            <SearchIcon size={15} aria-hidden />
            <span className="sr-only">{c.agents.search}</span>
            <input
              ref={search}
              className="input"
              type="search"
              placeholder={c.agents.search}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              data-testid="agents-search"
            />
          </label>
          <div
            className="filters"
            role="group"
            aria-label={c.agents.filterLabel}
          >
            {filters.map((f) => (
              <button
                key={f}
                type="button"
                className="filter"
                aria-pressed={filter === f}
                onClick={() => setFilter(f)}
                data-testid={`agents-filter-${f}`}
              >
                {f === "all" ? c.agents.all : c.agents.status[f]}
                <span className="n">{counts[f] ?? 0}</span>
              </button>
            ))}
          </div>
          <span className="grow" />
          <button
            type="button"
            className="btn solid"
            onClick={() => studio.go({ view: "agent", id: null })}
            data-testid="agents-new"
          >
            <PlusIcon size={16} aria-hidden />
            {c.agents.newAgent}
          </button>
        </div>
        {content}
      </div>
      <footer className="m-foot">
        <span className="hint">
          <Kbd>/</Kbd> {c.agents.hints.search} <Kbd>N</Kbd>{" "}
          {c.agents.hints.newAgent} <Kbd>Esc</Kbd> {c.agents.hints.close}
        </span>
        <span className="grow" />
        <span className="hint">{c.agents.running(running)}</span>
      </footer>
    </div>
  );
}

function AgentCard({
  agent,
  status,
  runs,
  integrations,
}: {
  agent: Agent;
  status: AgentStatus | null;
  runs: Parameters<typeof nextRunLine>[1];
  integrations: CatalogIntegration[] | undefined;
}) {
  const c = useStudioCopy();
  const studio = useStudio();
  const title = agentTitle(agent);
  const assigned = (agent.tools?.integrations ?? [])
    .map(
      (id) =>
        integrations?.find((i) => i.id === id) ?? {
          id,
          name: id.split(":").slice(1).join(":"),
        },
    )
    .slice(0, 3);
  const skills = agent.skills;
  return (
    <button
      type="button"
      className="acard"
      onClick={() => studio.go({ view: "agent", id: agent.name })}
      aria-label={c.agents.editAria(title)}
      data-testid={`agent-card-${agent.name}`}
    >
      <div className="top">
        <Av id={avatarIdFor(agent.name, agent.avatar)} size={44} />
        <div className="grow">
          <div
            className="row"
            style={{ justifyContent: "space-between", gap: 8 }}
          >
            <span className="nm">{title}</span>
            {status ? <StatusPill status={status} /> : null}
          </div>
          <div className="pp" style={{ marginTop: 4 }}>
            {agent.description}
          </div>
        </div>
      </div>
      <div className="meta">
        {status === "ondemand" ? (
          <MessageSquareIcon size={14} aria-hidden />
        ) : (
          <ClockIcon size={14} aria-hidden />
        )}
        <span className="grow">{nextRunLine(status, runs)}</span>
        {assigned.length ? (
          <span
            className="monos"
            title={assigned.map((i) => i.name).join(", ")}
          >
            {assigned.map((i) => (
              <Mono key={i.id} integration={i} />
            ))}
          </span>
        ) : null}
        {assigned.length ? (
          <span className="sep" aria-hidden>
            ·
          </span>
        ) : null}
        <span>
          {skills === null
            ? c.agents.allSkills
            : c.agents.skills(skills.length)}
        </span>
      </div>
    </button>
  );
}

/** The lead agent: its instructions and tools are fixed; its grants and its
 * schedules (the automations that name no agent) are edited here. */
function LeadCard() {
  const c = useStudioCopy();
  const studio = useStudio();
  const { runs } = useAgentRuns(LEAD_AGENT_ID);
  const status = agentStatus("lead", runs);
  return (
    <button
      type="button"
      className="acard"
      onClick={() => studio.go({ view: "agent", id: LEAD_AGENT_ID })}
      aria-label={c.agents.editAria(c.agents.lead)}
      data-testid="agent-card-lead_agent"
    >
      <div className="top">
        <Av id={LEAD_AVATAR} size={44} />
        <div className="grow">
          <div
            className="row"
            style={{ justifyContent: "space-between", gap: 8 }}
          >
            <span className="nm">{c.agents.lead}</span>
            {status ? <StatusPill status={status} /> : null}
          </div>
          <div className="pp" style={{ marginTop: 4 }}>
            {c.agents.leadPurpose}
          </div>
        </div>
      </div>
      <div className="meta">
        {status === "ondemand" ? (
          <MessageSquareIcon size={14} aria-hidden />
        ) : (
          <ClockIcon size={14} aria-hidden />
        )}
        <span className="grow">{nextRunLine(status, runs)}</span>
        <span>{c.agents.allSkills}</span>
      </div>
    </button>
  );
}
