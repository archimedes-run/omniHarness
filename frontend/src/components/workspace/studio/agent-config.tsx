"use client";

import {
  BookOpenIcon,
  CheckIcon,
  ChevronRightIcon,
  ExternalLinkIcon,
  HandIcon,
  InfoIcon,
  LockIcon,
  PlugIcon,
  PlusIcon,
  SearchIcon,
  ShieldIcon,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { useSkills } from "@/core/skills/hooks";
import {
  asksFirst,
  countSelection,
  usable,
  type AutonomyView,
  type CatalogIntegration,
  type CatalogTool,
  type IntegrationKind,
  type Tier,
  type ToolCatalog,
} from "@/core/studio";
import { sameSelection } from "@/core/studio/tool-select";

import type { AgentForm } from "./agent-form";
import { useStudioCopy } from "./copy";
import { Glyph, Mono, Pill, Switch, TierBadge, skillLook, cx } from "./parts";
import { useStudio } from "./studio";

export type ConfigPanel = "integrations" | "skills" | "autonomy";

/** The tools whose name says they save an email draft (the "drafts" grant
 * covers exactly these; app/policy/grants.py). */
const DRAFT_TOOLS = new Set([
  "connector-gmail_GMAIL_CREATE_EMAIL_DRAFT",
  "gmail_create_draft",
  "gmail_draft_email",
]);

export function AgentConfigStep({
  form,
  orig,
  patch,
  isNew,
  isLead,
  legacy,
  panel,
  onPanel,
  catalog,
  catalogError,
  autonomy,
  autonomyError,
  suggestedGrants,
}: {
  form: AgentForm;
  orig: AgentForm;
  patch: (p: Partial<AgentForm>) => void;
  isNew: boolean;
  isLead: boolean;
  legacy: boolean;
  panel: ConfigPanel;
  onPanel: (p: ConfigPanel) => void;
  catalog: ToolCatalog | undefined;
  catalogError: Error | null;
  autonomy: AutonomyView | undefined;
  autonomyError: Error | null;
  suggestedGrants: string[];
}) {
  const c = useStudioCopy();
  const a = c.agent;
  const selection = form.selection ?? {};
  const counts = countSelection(selection);
  const t3 = asksFirst(selection, catalog);
  const grantable = (autonomy?.classes ?? []).filter((k) => k.grantable);
  const panels: ConfigPanel[] = isLead
    ? ["autonomy"]
    : ["integrations", "skills", "autonomy"];
  const current = panels.includes(panel) ? panel : panels[0]!;
  const tabs = useRef<HTMLDivElement>(null);

  const changed = (p: ConfigPanel) => {
    if (isNew) return false;
    if (p === "integrations")
      return (
        form.toolsTouched &&
        !!form.selection &&
        !!orig.selection &&
        !sameSelection(form.selection, orig.selection)
      );
    if (p === "skills")
      return JSON.stringify(form.skills) !== JSON.stringify(orig.skills);
    return [...form.grants].sort().join() !== [...orig.grants].sort().join();
  };
  const cards: [ConfigPanel, typeof PlugIcon, string, string][] = [
    [
      "integrations",
      PlugIcon,
      a.cards.integrations,
      legacy && !form.toolsTouched
        ? a.cLegacyTools
        : a.cardIntegrations(counts.integrations, counts.tools),
    ],
    [
      "skills",
      BookOpenIcon,
      a.cards.skills,
      a.cardSkills(form.skills === null ? null : form.skills.length),
    ],
    [
      "autonomy",
      ShieldIcon,
      a.cards.autonomy,
      a.cardAutonomy(
        form.grants.filter((g) => grantable.some((k) => k.id === g)).length,
        grantable.length,
        t3.length,
      ),
    ],
  ];

  return (
    <div data-testid="agent-step-config">
      <div
        className="cfg-cards"
        role="tablist"
        aria-label={a.config}
        ref={tabs}
        onKeyDown={(e) => {
          const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
          if (!d) return;
          e.preventDefault();
          const i = panels.indexOf(current);
          const next = panels[(i + d + panels.length) % panels.length]!;
          onPanel(next);
          tabs.current?.querySelector<HTMLElement>(`#tab-${next}`)?.focus();
        }}
      >
        {cards
          .filter(([k]) => panels.includes(k))
          .map(([k, Icon, title, caption]) => (
            <button
              key={k}
              type="button"
              className="cfg"
              role="tab"
              id={`tab-${k}`}
              aria-controls={`panel-${k}`}
              aria-selected={current === k}
              tabIndex={current === k ? 0 : -1}
              onClick={() => onPanel(k)}
              data-testid={`config-tab-${k}`}
            >
              <span className="corner">
                {changed(k) ? (
                  <span className="dirty-dot" title={c.edited} />
                ) : null}
                {current === k ? <CheckIcon size={16} aria-hidden /> : null}
              </span>
              <span className="ico" aria-hidden>
                <Icon size={18} />
              </span>
              <span>
                <span className="t">{title}</span>
                <span className="c">{caption}</span>
              </span>
            </button>
          ))}
      </div>
      <section
        role="tabpanel"
        id={`panel-${current}`}
        aria-labelledby={`tab-${current}`}
      >
        {current === "integrations" ? (
          <IntegrationsPanel
            form={form}
            patch={patch}
            legacy={legacy}
            catalog={catalog}
            error={catalogError}
          />
        ) : current === "skills" ? (
          <SkillsPanel form={form} patch={patch} />
        ) : (
          <AutonomyPanel
            form={form}
            patch={patch}
            autonomy={autonomy}
            error={autonomyError}
            catalog={catalog}
            suggested={suggestedGrants}
            isLead={isLead}
          />
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Integrations
// ---------------------------------------------------------------------------

const GROUP_ORDER: IntegrationKind[] = ["app", "mcp", "custom", "builtin"];

function IntegrationsPanel({
  form,
  patch,
  legacy,
  catalog,
  error,
}: {
  form: AgentForm;
  patch: (p: Partial<AgentForm>) => void;
  legacy: boolean;
  catalog: ToolCatalog | undefined;
  error: Error | null;
}) {
  const c = useStudioCopy();
  const a = c.agent;
  const [q, setQ] = useState("");
  const [tier, setTier] = useState<0 | Tier>(0);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [all, setAll] = useState<Set<string>>(new Set());
  const selection = form.selection ?? {};
  const counts = countSelection(selection);

  if (error)
    return (
      <p className="err" role="alert">
        {a.catalogFailed(error.message)}
      </p>
    );
  if (!catalog || !form.selection)
    return (
      <p className="help" role="status">
        {a.catalogLoading}
      </p>
    );

  const needle = q.trim().toLowerCase();
  const total = catalog.integrations
    .filter(usable)
    .reduce((n, i) => n + i.tools.length, 0);
  const matches = (i: CatalogIntegration, t: CatalogTool) =>
    (!tier || t.tier === tier) &&
    (!needle ||
      `${i.name} ${t.label} ${t.short} ${t.name}`
        .toLowerCase()
        .includes(needle));
  const setTools = (id: string, tools: string[]) =>
    patch({ selection: { ...selection, [id]: tools }, toolsTouched: true });
  const toggle = (
    set: Set<string>,
    id: string,
    write: (s: Set<string>) => void,
  ) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    write(next);
  };

  const row = (i: CatalogIntegration) => {
    const filtering = !!needle || !!tier;
    const visible = i.tools.filter((t) => matches(i, t));
    if (filtering && !visible.length) return null;
    const on = new Set(selection[i.id] ?? []);
    const n = i.tools.filter((t) => on.has(t.name)).length;
    const live = usable(i);
    const offerable = i.tools.filter((t) => t.tier !== null);
    const state: boolean | "mixed" =
      !live || n === 0 ? false : n === offerable.length ? true : "mixed";
    const expanded = live && (open.has(i.id) || filtering);
    const showAll = all.has(i.id) || filtering;
    const listed = showAll ? visible : visible.filter((t) => t.common);
    const hidden = visible.length - listed.length;
    const status =
      i.status === "connected" ? (
        <Pill tone="good" dot>
          {a.status.connected}
        </Pill>
      ) : i.status === "unreachable" ? (
        <Pill tone="warn" dot>
          {a.status.unreachable}
        </Pill>
      ) : (
        <Pill tone="muted">{a.status[i.status]}</Pill>
      );
    return (
      <div
        className={cx("int", expanded && "open", !n && "off")}
        key={i.id}
        data-testid={`integration-${i.id}`}
      >
        <div className="int-row">
          <button
            type="button"
            className="exp"
            onClick={() => toggle(open, i.id, setOpen)}
            aria-expanded={expanded}
            aria-controls={`tools-${i.id}`}
            aria-label={a.showTools(!expanded, i.name)}
            disabled={!live}
            style={live ? undefined : { visibility: "hidden" }}
            data-testid={`integration-expand-${i.id}`}
          >
            <ChevronRightIcon size={16} aria-hidden />
          </button>
          <Mono integration={i} lg />
          <div className="grow">
            <div className="nm">
              {i.name} {status}
            </div>
            <div className="ds">{i.detail}</div>
          </div>
          {live ? (
            <>
              <span className="cnt">{a.nOfTools(n, i.tools.length)}</span>
              <Switch
                checked={state}
                onChange={() => {
                  if (n) setTools(i.id, []);
                  else {
                    // On: what does not ask first, ticked; the rest stay for the person.
                    setTools(
                      i.id,
                      i.tools
                        .filter((t) => t.tier !== null && t.tier < 3)
                        .map((t) => t.name),
                    );
                    setOpen((s) => new Set(s).add(i.id));
                  }
                }}
                label={a.allow(i.name)}
                testId={`integration-switch-${i.id}`}
              />
            </>
          ) : i.kind === "app" ? (
            <a
              className="btn sm"
              href="/workspace/connections"
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLinkIcon size={13} aria-hidden />
              {a.connect}
            </a>
          ) : null}
        </div>
        {expanded ? (
          <div className="tools" id={`tools-${i.id}`}>
            {i.id === "connector:GMAIL" || i.id === "local:gmail" ? (
              <div className="int-note">
                <InfoIcon size={14} aria-hidden />
                {a.gmailNote}
              </div>
            ) : null}
            {listed.map((t) => {
              const checked = on.has(t.name);
              return (
                <div
                  className="tool"
                  key={t.name}
                  data-testid={`tool-${t.name}`}
                  data-tier={t.tier ?? "none"}
                >
                  <div>
                    <div className="tl">
                      {t.label} <span className="tid">{t.short}</span>
                    </div>
                    {t.description ? (
                      <div className="td">{t.description}</div>
                    ) : null}
                    {t.tier === 3 && checked ? (
                      <div className="wait">
                        <HandIcon size={12} aria-hidden />
                        {a.waitsOnHome}
                      </div>
                    ) : null}
                  </div>
                  <TierBadge tier={t.tier} />
                  <Switch
                    checked={checked && t.tier !== null}
                    disabled={t.tier === null}
                    onChange={() =>
                      setTools(
                        i.id,
                        checked
                          ? [...on].filter((x) => x !== t.name)
                          : [...on, t.name],
                      )
                    }
                    label={a.toolSwitch(t.label, i.name)}
                    testId={`tool-switch-${t.name}`}
                  />
                </div>
              );
            })}
            {hidden > 0 ||
            (all.has(i.id) && !filtering && visible.some((t) => !t.common)) ? (
              <button
                type="button"
                className="link"
                style={{ margin: "6px 0" }}
                onClick={() => toggle(all, i.id, setAll)}
                data-testid={`integration-all-${i.id}`}
              >
                {all.has(i.id) ? a.showFewer : a.showAll(i.tools.length)}
              </button>
            ) : null}
            <div className="bulk">
              <span>{a.quickSet}</span>
              {(
                [
                  [1, a.readsOnly],
                  [2, a.readsRoutine],
                  [3, a.everythingClassified],
                  [0, a.none],
                ] as const
              ).map(([max, label]) => (
                <button
                  key={label}
                  type="button"
                  className="link"
                  onClick={() =>
                    setTools(
                      i.id,
                      max
                        ? i.tools
                            .filter((t) => t.tier !== null && t.tier <= max)
                            .map((t) => t.name)
                        : [],
                    )
                  }
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    );
  };

  const tierFilters: (0 | Tier)[] = [0, 1, 2, 3];
  const anyMatch = catalog.integrations.some((i) =>
    i.tools.some((t) => matches(i, t)),
  );
  return (
    <div data-testid="integrations-panel">
      <div className="row wrap" style={{ marginBottom: 12, gap: 12 }}>
        <div className="grow">
          <h3 className="sec-title">
            {a.whichTools(form.name.trim() || a.thisAgent)}
          </h3>
          <p className="sec-sub" style={{ margin: 0 }}>
            {a.toolsSub(counts.tools, total, counts.integrations)}
          </p>
        </div>
        <label className="with-ico" style={{ width: 240 }}>
          <SearchIcon size={15} aria-hidden />
          <span className="sr-only">{a.searchTools}</span>
          <input
            className="input"
            type="search"
            placeholder={a.searchTools}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            data-testid="tools-search"
          />
        </label>
      </div>
      {legacy && !form.toolsTouched ? (
        <div
          className="note"
          style={{ marginBottom: 12 }}
          data-testid="legacy-note"
        >
          <InfoIcon size={16} aria-hidden />
          <div>{a.legacyNote}</div>
        </div>
      ) : null}
      {catalog.rules_error ? (
        <div className="note" style={{ marginBottom: 12 }}>
          <InfoIcon size={16} aria-hidden />
          <div>{a.rulesUnreadable(catalog.rules_error)}</div>
        </div>
      ) : null}
      <div
        className="legend panel raised"
        role="group"
        aria-label={a.tiersLabel}
      >
        <span style={{ fontWeight: 500 }}>{a.tiers}</span>
        {tierFilters.map((k) => (
          <button
            key={k}
            type="button"
            className="filter"
            aria-pressed={tier === k}
            onClick={() => setTier(k)}
            style={{
              height: 28,
              fontSize: 12,
              padding: `0 8px 0 ${k ? 4 : 10}px`,
            }}
            data-testid={`tier-filter-${k}`}
          >
            {k ? <TierBadge tier={k} /> : c.agents.all}
            {k ? <span>{a.tierMeaning[k]}</span> : null}
          </button>
        ))}
      </div>
      {GROUP_ORDER.map((kind) => {
        const rows = catalog.integrations
          .filter((i) => i.kind === kind)
          .map(row)
          .filter(Boolean);
        if (!rows.length) return null;
        return (
          <div key={kind}>
            <div className="group-h">
              {a.groups[kind]}
              {kind === "app" ? (
                <span
                  style={{
                    fontWeight: 500,
                    textTransform: "none",
                    letterSpacing: 0,
                  }}
                >
                  {a.viaComposio}
                </span>
              ) : null}
              {kind === "app" ? (
                <a
                  className="link"
                  href="/workspace/connections"
                  target="_blank"
                  rel="noreferrer"
                >
                  {a.manageConnections}{" "}
                  <ExternalLinkIcon size={12} aria-hidden />
                </a>
              ) : kind === "custom" ? (
                <a
                  className="link"
                  href="/workspace/connections"
                  target="_blank"
                  rel="noreferrer"
                >
                  {a.addServer} <ExternalLinkIcon size={12} aria-hidden />
                </a>
              ) : null}
            </div>
            {rows}
          </div>
        );
      })}
      {needle && !anyMatch ? (
        <div className="empty-search">{a.noToolsMatch(q)}</div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skills
// ---------------------------------------------------------------------------

function SkillsPanel({
  form,
  patch,
}: {
  form: AgentForm;
  patch: (p: Partial<AgentForm>) => void;
}) {
  const c = useStudioCopy();
  const a = c.agent;
  const studio = useStudio();
  const { skills } = useSkills();
  const [q, setQ] = useState("");
  const enabled = useMemo(
    () => skills.filter((s) => s.enabled).map((s) => s.name),
    [skills],
  );
  const effective = form.skills ?? enabled;
  const needle = q.trim().toLowerCase();
  const shown = skills.filter(
    (s) =>
      !needle || `${s.name} ${s.description}`.toLowerCase().includes(needle),
  );
  return (
    <div data-testid="skills-panel">
      <div className="row wrap" style={{ marginBottom: 12, gap: 12 }}>
        <div className="grow">
          <h3 className="sec-title">{a.skillsTitle}</h3>
          <p className="sec-sub" style={{ margin: 0 }}>
            {a.skillsSub}
          </p>
        </div>
        <label className="with-ico" style={{ width: 220 }}>
          <SearchIcon size={15} aria-hidden />
          <span className="sr-only">{a.searchSkills}</span>
          <input
            className="input"
            type="search"
            placeholder={a.searchSkills}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="btn sm"
          onClick={() => studio.go({ view: "skill", id: null })}
        >
          <PlusIcon size={14} aria-hidden />
          {a.newSkill}
        </button>
      </div>
      {form.skills === null ? (
        <div className="note" style={{ marginBottom: 12 }}>
          <InfoIcon size={16} aria-hidden />
          <div>{a.allSkillsNote}</div>
        </div>
      ) : null}
      {shown.map((s) => {
        const on = effective.includes(s.name);
        const look = skillLook(s.name, null, null);
        const title = s.name
          .replace(/[-_]+/g, " ")
          .replace(/^./, (x) => x.toUpperCase());
        return (
          <div
            className={cx("sk", on && "on")}
            key={s.name}
            data-testid={`skill-row-${s.name}`}
          >
            <Glyph icon={look.icon} color={look.color} />
            <div className="grow">
              <div className="nm">
                {title}
                {s.category !== "custom" ? (
                  <span className="pill muted">{a.builtIn}</span>
                ) : null}
              </div>
              <div className="when">
                <b>{a.usedWhen}</b> {s.description}
              </div>
            </div>
            <button
              type="button"
              className="link"
              onClick={() => studio.go({ view: "skill", id: s.name })}
            >
              {a.open}
            </button>
            <Switch
              checked={on}
              onChange={() =>
                patch({
                  skills: on
                    ? effective.filter((x) => x !== s.name)
                    : [...effective, s.name],
                })
              }
              label={a.allowSkill(title)}
              testId={`skill-switch-${s.name}`}
            />
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Autonomy
// ---------------------------------------------------------------------------

function AutonomyPanel({
  form,
  patch,
  autonomy,
  error,
  catalog,
  suggested,
  isLead,
}: {
  form: AgentForm;
  patch: (p: Partial<AgentForm>) => void;
  autonomy: AutonomyView | undefined;
  error: Error | null;
  catalog: ToolCatalog | undefined;
  suggested: string[];
  isLead: boolean;
}) {
  const c = useStudioCopy();
  const a = c.agent;
  if (error)
    return (
      <p className="err" role="alert">
        {a.autonomyFailed(error.message)}
      </p>
    );
  if (!autonomy) return <p className="help">{c.agents.loading}</p>;
  const selection = form.selection ?? {};
  const t3 = asksFirst(selection, catalog);
  const hasDraftTool = Object.values(selection).some((tools) =>
    tools.some((t) => DRAFT_TOOLS.has(t)),
  );
  const classes = autonomy.classes.filter(
    (k) => k.grantable || form.grants.includes(k.id),
  );
  return (
    <div
      className="two"
      style={{ gridTemplateColumns: "1.25fr 1fr" }}
      data-testid="autonomy-panel"
    >
      <div>
        <h3 className="sec-title">{a.autonomyTitle}</h3>
        <p className="sec-sub">{a.autonomySub}</p>
        <div role="group" aria-label={a.autonomyGroup}>
          {classes.map((k) => {
            const needsTool = k.id === "drafts" && !hasDraftTool && !isLead;
            const disabled = !k.grantable || needsTool;
            const on = form.grants.includes(k.id) && !disabled;
            const toggle = () => {
              if (disabled) return;
              patch({
                grants: on
                  ? form.grants.filter((g) => g !== k.id)
                  : [...form.grants, k.id],
              });
            };
            return (
              <div
                key={k.id}
                className={cx("grant", on && "on")}
                role="checkbox"
                tabIndex={0}
                aria-checked={on}
                aria-disabled={disabled || undefined}
                onClick={toggle}
                onKeyDown={(e) => {
                  if (e.key === " " || e.key === "Enter") {
                    e.preventDefault();
                    toggle();
                  }
                }}
                data-testid={`grant-${k.id}`}
              >
                <span className={cx("check", on && "on")} aria-hidden>
                  {on ? <CheckIcon size={12} /> : null}
                </span>
                <div>
                  <div className="gt">
                    {k.label} <TierBadge tier={2} />
                    {suggested.includes(k.id) && !on ? (
                      <span className="pill accent">{a.suggested}</span>
                    ) : null}
                  </div>
                  <div className="gd">
                    {needsTool
                      ? a.draftNeedsTool
                      : k.grantable
                        ? k.allows
                        : k.not_grantable_reason}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        <div className="row" style={{ marginTop: 16, gap: 14 }}>
          <div>
            <div style={{ fontWeight: 500 }}>
              {a.capLine(autonomy.cap_per_run)}
            </div>
            <div className="help">{a.capHelp}</div>
          </div>
        </div>
      </div>
      <div className="stack">
        <div className="waits">
          <div className="wh">
            <LockIcon size={16} aria-hidden />
            {a.alwaysWaits}
          </div>
          <p
            className="help"
            style={{ margin: "4px 0 10px", color: "var(--foreground-2)" }}
          >
            {a.alwaysWaitsHelp}
          </p>
          <div className="row wrap" style={{ gap: 6 }}>
            {t3.length ? (
              t3.map(({ integration, label, name }) => (
                <span className="chip" key={name}>
                  <Mono integration={integration} />
                  {label}
                </span>
              ))
            ) : (
              <span className="help">{a.noneAsk}</span>
            )}
          </div>
          <p className="help" style={{ margin: "10px 0 0" }}>
            {a.alwaysWaitsMore}
          </p>
        </div>
        <div className="note">
          <InfoIcon size={16} aria-hidden />
          <div>{a.loggedNote}</div>
        </div>
      </div>
    </div>
  );
}
