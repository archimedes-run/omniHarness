"use client";

import * as SwitchPrimitive from "@radix-ui/react-switch";
import { useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNowStrict } from "date-fns";
import { CodeXmlIcon, LockIcon, PaperclipIcon, SearchIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { BrandLogo, resolveBrand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Agent } from "@/core/agents/types";
import type { Project } from "@/core/ledger/types";
import { connectComposioToolkit } from "@/core/mcp/connect";
import { cn } from "@/lib/utils";

import { AgentAvatar } from "./agent-avatar";
import type { PickerTab } from "./commands";
import {
  connectWords,
  rowAction,
  statusLine,
  type ConnectPhase,
  type IntegrationRow,
  type StatusWord,
} from "./logic";

const ago = (iso: string) =>
  formatDistanceToNowStrict(new Date(iso), { addSuffix: true });

export const MCP_SUITE_HREF = "/workspace/connections";

/** Open Question 8: "@" calls in a second agent only with Phase 2. */
export const MULTI_AGENT_LATER =
  "Calling another agent into a chat arrives with multi-agent chat.";

export const agentChatHref = (name: string) =>
  `/workspace/agents/${encodeURIComponent(name)}/chats/new`;

const TABS: { id: PickerTab; label: string }[] = [
  { id: "projects", label: "Projects" },
  { id: "agents", label: "Agents" },
  { id: "integrations", label: "Integrations" },
  { id: "skills", label: "Skills" },
  { id: "files", label: "Files" },
];

/** design-notes.md §Status vocabulary: the colour for each word. */
const STATUS_CLASS: Record<StatusWord, string> = {
  Live: "text-success",
  Connected: "text-success",
  Off: "text-muted-foreground",
  Unreachable: "text-warning",
  "Not connected": "text-muted-foreground",
  "Not checked yet": "text-muted-foreground",
  "Status unknown": "text-muted-foreground",
};

export interface PickerProps {
  /** Above the bar in a chat; below it on the centred new-chat layout. */
  placement?: "top" | "bottom";
  /** A new chat (nothing sent yet): no project link yet, "@" starts a chat. */
  isNewChat: boolean;
  tab: PickerTab;
  onTabChange: (tab: PickerTab) => void;
  onClose: () => void;
  // Projects
  projects: { id: string; name: string; status: string }[];
  attachedProjects: { link_id: string; project: Project }[];
  onAttachProject: (id: string) => void;
  // Agents
  agents: Agent[];
  agentsError?: unknown;
  threadAgent: string;
  /** A new chat on the plain chat page: an agent is picked in place. */
  canChooseAgent?: boolean;
  onChooseAgent?: (name: string) => void;
  // Integrations
  integrations: IntegrationRow[];
  integrationsLoading: boolean;
  integrationsError?: unknown;
  statusError?: unknown;
  connectorsAvailable: boolean;
  overCap: boolean;
  count: { count: number; cap: number } | null;
  onToggleIntegration: (id: string, on: boolean) => void;
  // Skills
  skills: { name: string; description: string }[];
  skillsError?: unknown;
  /** Skills removed from this chat; the bar's chips show the rest. */
  excludedSkills?: string[];
  /** Which skills this chat removed could not be read: no switches then. */
  chatSkillsError?: unknown;
  onToggleSkill?: (name: string, on: boolean) => void;
  // Files
  files: { id: string; filename?: string }[];
  uploaded: { filename: string }[];
  onAttachFiles: () => void;
  onRemoveFile: (id: string) => void;
}

/**
 * The "+" picker (Chat-Picker.dc.html): one dialog, five tabs. A real tablist
 * (Radix: arrow keys move between tabs), focus kept inside while open, Esc
 * closes and focus returns to the "+" button (the caller's job, on close).
 */
export function ContextPicker(props: PickerProps) {
  const { tab, onTabChange, onClose } = props;
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const panel = panelRef.current;
    panel
      ?.querySelector<HTMLElement>('[role="tab"][data-state="active"]')
      ?.focus();
    const onDown = (e: MouseEvent) => {
      if (panel && !panel.contains(e.target as Node)) {
        const opener = (e.target as HTMLElement).closest(
          "[data-chat-picker-trigger]",
        );
        if (!opener) onClose();
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onClose]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !panelRef.current) return;
    const focusable = [
      ...panelRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ].filter((el) => el.offsetParent !== null);
    if (focusable.length === 0) return;
    const first = focusable[0]!;
    const last = focusable[focusable.length - 1]!;
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label="Add context"
      data-testid="context-picker"
      onKeyDown={onKeyDown}
      className={cn(
        "bg-card text-card-foreground border-input absolute inset-x-0 z-50 flex max-h-[62vh] flex-col overflow-hidden rounded-xl border text-sm shadow-xl",
        props.placement === "bottom" ? "top-full mt-2.5" : "bottom-full mb-2.5",
      )}
    >
      <Tabs
        value={tab}
        onValueChange={(v) => onTabChange(v as PickerTab)}
        className="min-h-0 gap-0"
      >
        <div className="border-border border-b p-2">
          <TabsList
            aria-label="Context type"
            className="h-auto flex-wrap bg-transparent p-0"
          >
            {TABS.map((t) => (
              <TabsTrigger
                key={t.id}
                value={t.id}
                className="data-[state=active]:bg-primary-subtle dark:data-[state=active]:bg-primary-subtle data-[state=active]:text-foreground text-foreground-2 dark:text-foreground-2 min-h-9 flex-none rounded-md border-0 px-3 py-1.5 font-normal data-[state=active]:font-medium data-[state=active]:shadow-none max-sm:min-h-11"
              >
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <div className="min-h-0 overflow-y-auto">
          <TabsContent value="projects">
            <ProjectsTab {...props} />
          </TabsContent>
          <TabsContent value="agents">
            <AgentsTab {...props} />
          </TabsContent>
          <TabsContent value="integrations">
            <IntegrationsTab {...props} />
          </TabsContent>
          <TabsContent value="skills">
            <SkillsTab {...props} />
          </TabsContent>
          <TabsContent value="files">
            <FilesTab {...props} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}

function SearchBox({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="px-3 pt-2.5 pb-2">
      <label className="bg-surface-raised flex items-center gap-2 rounded-lg px-2.5 py-2">
        <SearchIcon className="text-muted-foreground size-3.5" aria-hidden />
        <span className="sr-only">{label}</span>
        <input
          type="search"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={label}
          className="placeholder:text-muted-foreground w-full bg-transparent text-sm outline-none"
        />
      </label>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-muted-foreground px-4 py-6 text-center text-sm">
      {children}
    </p>
  );
}

function Problem({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-destructive px-4 py-2 text-sm" role="alert">
      {children}
    </p>
  );
}

function Row({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <li
      className={cn(
        "flex min-h-11 items-center gap-3 rounded-md px-2.5 py-1.5",
        className,
      )}
    >
      {children}
    </li>
  );
}

function useFilter<T>(items: T[], text: (t: T) => string) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? items.filter((i) => text(i).toLowerCase().includes(q)) : items;
  }, [items, query, text]);
  return { query, setQuery, filtered };
}

const agentText = (a: Agent) => `${a.name} ${a.description}`;
const rowText = (r: IntegrationRow) => r.name;
const skillText = (s: { name: string; description: string }) =>
  `${s.name} ${s.description}`;

function ProjectsTab({
  projects,
  attachedProjects,
  onAttachProject,
  isNewChat,
}: PickerProps) {
  if (isNewChat) {
    return (
      <Empty>Send the first message, then attach this chat to a project.</Empty>
    );
  }
  const attachedIds = new Set(attachedProjects.map((a) => a.project.id));
  const open = projects.filter((p) => p.status !== "archived");
  return (
    <ul className="flex flex-col p-1.5" aria-label="Projects">
      {open.map((p) => (
        <Row key={p.id}>
          <span className="flex-1 truncate">{p.name}</span>
          {attachedIds.has(p.id) ? (
            <span className="text-muted-foreground text-xs">In this chat</span>
          ) : (
            <Button
              size="sm"
              variant="outline"
              onClick={() => onAttachProject(p.id)}
            >
              Attach<span className="sr-only"> to {p.name}</span>
            </Button>
          )}
        </Row>
      ))}
      {open.length === 0 && (
        <li>
          <Empty>
            No projects yet.{" "}
            <Link className="text-primary underline" href="/workspace/projects">
              Create one
            </Link>
          </Empty>
        </li>
      )}
    </ul>
  );
}

function AgentsTab({
  agents,
  agentsError,
  isNewChat,
  threadAgent,
  canChooseAgent,
  onChooseAgent,
}: PickerProps) {
  const { query, setQuery, filtered } = useFilter(agents, agentText);
  return (
    <>
      <SearchBox label="Search agents" value={query} onChange={setQuery} />
      {!isNewChat && (
        <p className="text-muted-foreground px-4 pb-1 text-xs">
          {MULTI_AGENT_LATER}
        </p>
      )}
      {agentsError ? <Problem>Agents could not be loaded.</Problem> : null}
      <ul className="flex flex-col px-1.5 pb-1.5" aria-label="Agents">
        {filtered.map((a) => (
          <Row key={a.name}>
            <AgentAvatar id={a.name} name={a.name} />
            <span className="min-w-0 flex-1">
              <span className="block truncate">{a.name}</span>
              {a.description && (
                <span className="text-muted-foreground block truncate text-xs">
                  {a.description}
                </span>
              )}
            </span>
            {a.name === threadAgent ? (
              <span className="text-muted-foreground text-xs">
                In this chat
              </span>
            ) : canChooseAgent && onChooseAgent ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => onChooseAgent(a.name)}
              >
                Use<span className="sr-only"> {a.name} for this chat</span>
              </Button>
            ) : isNewChat ? (
              <Button size="sm" variant="outline" asChild>
                <Link href={agentChatHref(a.name)}>
                  Start chat<span className="sr-only"> with {a.name}</span>
                </Link>
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                disabled
                title={MULTI_AGENT_LATER}
              >
                Call in<span className="sr-only"> {a.name}</span>
              </Button>
            )}
          </Row>
        ))}
        {!agentsError && agents.length === 0 && (
          <li>
            <Empty>No agents yet.</Empty>
          </li>
        )}
        <li className="border-border mt-1 border-t pt-1">
          <Link
            href="/workspace/agents/new"
            className="text-foreground-2 hover:bg-accent flex min-h-11 items-center gap-3 rounded-md px-2.5 text-sm"
          >
            <span aria-hidden className="w-[26px] text-center">
              +
            </span>
            Create an agent
          </Link>
        </li>
      </ul>
    </>
  );
}

/**
 * Chat-Picker.dc.html's switch: 36 x 20, the accent track with a dark thumb
 * when on, a raised track with a strong border and a muted thumb when off.
 */
function PickerSwitch(
  props: React.ComponentProps<typeof SwitchPrimitive.Root>,
) {
  return (
    <SwitchPrimitive.Root
      className="data-[state=checked]:bg-primary data-[state=unchecked]:bg-surface-raised data-[state=unchecked]:border-border-strong focus-visible:ring-ring inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-transparent px-px transition-colors outline-none focus-visible:ring-2 focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
      {...props}
    >
      <SwitchPrimitive.Thumb className="data-[state=checked]:bg-primary-foreground data-[state=unchecked]:bg-muted-foreground pointer-events-none block size-4 rounded-full transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0" />
    </SwitchPrimitive.Root>
  );
}

/**
 * A row's logo: the brand's own mark in a 28 px tile (radius 7). A local MCP
 * server with no brand gets the board's code tile, named after the server.
 */
function SourceLogo({ row }: { row: IntegrationRow }) {
  const branded = resolveBrand(row.logoSource) ?? resolveBrand(row.name);
  if (row.kind === "local" && !branded) {
    return (
      <span
        role="img"
        aria-label={`${row.name}, a local MCP server`}
        className="bg-surface-raised text-foreground-2 inline-flex size-7 shrink-0 items-center justify-center rounded-[7px]"
        data-brand="local-server"
      >
        <CodeXmlIcon className="size-4" aria-hidden />
      </span>
    );
  }
  return (
    <BrandLogo
      source={row.logoSource}
      name={row.name}
      size={28}
      className="rounded-[7px]"
    />
  );
}

/**
 * "Connect" on an app that is not connected: the same Composio sign-in pop-up
 * as MCP Suite (connectComposioToolkit), right here in the picker. Once it
 * completes, the live view is refetched and the row reads "Connected" with a
 * switch for this chat.
 */
function useInlineConnect() {
  const queryClient = useQueryClient();
  const [attempts, setAttempts] = useState<
    Record<string, { phase: ConnectPhase; detail?: string }>
  >({});
  const aborts = useRef(new Map<string, AbortController>());

  const set = (id: string, phase: ConnectPhase, detail?: string) =>
    setAttempts((prev) => ({ ...prev, [id]: { phase, detail } }));

  const connect = useCallback(
    (row: IntegrationRow) => {
      const toolkit = row.id.slice(row.id.indexOf(":") + 1);
      const abort = new AbortController();
      aborts.current.set(row.id, abort);
      set(row.id, "opening");
      connectComposioToolkit(toolkit, () => set(row.id, "waiting"), {
        signal: abort.signal,
      })
        .then((outcome) => {
          if (outcome === "connected" || outcome === "already-connected") {
            set(row.id, "connected");
            void queryClient.invalidateQueries({ queryKey: ["toolSources"] });
            void queryClient.invalidateQueries({ queryKey: ["tools"] });
          } else {
            set(row.id, outcome);
          }
        })
        .catch((err: unknown) =>
          set(
            row.id,
            "failed",
            err instanceof Error ? err.message : String(err),
          ),
        )
        .finally(() => aborts.current.delete(row.id));
    },
    [queryClient],
  );

  const cancel = useCallback((id: string) => {
    aborts.current.get(id)?.abort();
  }, []);

  return { attempts, connect, cancel };
}

const CONNECT_TONE = {
  muted: "text-muted-foreground",
  warn: "text-warning",
  bad: "text-destructive",
} as const;

// Chat-Picker.dc.html: the row's action is a 13 px underlined link.
const LINK_BUTTON =
  "text-primary inline-flex min-h-11 min-w-14 items-center justify-end text-[13px] underline underline-offset-2 disabled:opacity-60 focus-visible:ring-ring rounded-sm outline-none focus-visible:ring-2";

function IntegrationsTab({
  integrations,
  integrationsLoading,
  integrationsError,
  statusError,
  connectorsAvailable,
  overCap,
  count,
  onToggleIntegration,
}: PickerProps) {
  const { query, setQuery, filtered } = useFilter(integrations, rowText);
  const { attempts, connect, cancel } = useInlineConnect();
  return (
    <>
      <SearchBox
        label="Search integrations"
        value={query}
        onChange={setQuery}
      />
      {count && (
        <p
          className={cn(
            "px-4 pb-1 text-xs",
            overCap ? "text-destructive" : "text-muted-foreground",
          )}
          data-testid="tool-count"
        >
          {count.count} / {count.cap} tools for this model
          {overCap && ": at the limit. Turn one off before turning another on."}
        </p>
      )}
      {statusError ? (
        <p className="text-warning px-4 pb-1 text-xs" role="status">
          Live status could not be read, so each status is unknown.
        </p>
      ) : null}
      {!connectorsAvailable && (
        <p className="text-muted-foreground px-4 pb-1 text-xs">
          Apps need a Composio key.
        </p>
      )}
      {integrationsError ? (
        <Problem>This chat&apos;s integrations could not be loaded.</Problem>
      ) : null}
      {integrationsLoading && <Empty>Loading…</Empty>}
      <ul className="flex flex-col px-1.5 pb-1.5" aria-label="Integrations">
        {filtered.map((shown) => {
          const attempt = attempts[shown.id];
          // Sign-in just completed: Connected (reported by Composio) until
          // the refetched live view says the same or more.
          const row: IntegrationRow =
            attempt?.phase === "connected" && shown.status === "Not connected"
              ? { ...shown, status: "Connected" }
              : shown;
          const action = rowAction(row.status, row.kind);
          const inline =
            action.kind === "link" &&
            action.label === "Connect" &&
            row.kind === "connector";
          const busy =
            attempt?.phase === "opening" || attempt?.phase === "waiting";
          const words =
            inline && attempt
              ? connectWords(attempt.phase, attempt.detail)
              : null;
          return (
            <Row key={row.id}>
              <SourceLogo row={row} />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{row.name}</span>
                {row.status === "Unreachable" && row.error && (
                  <span
                    className="text-muted-foreground block truncate font-mono text-xs"
                    title={row.error}
                  >
                    {row.error}
                    {words && (
                      <span
                        className={cn(
                          "block text-xs",
                          CONNECT_TONE[words.tone],
                        )}
                        role={words.tone === "muted" ? "status" : "alert"}
                        data-testid="connect-message"
                      >
                        {words.text}
                      </span>
                    )}
                  </span>
                )}
                {words && (
                  <span
                    className={cn("block text-xs", CONNECT_TONE[words.tone])}
                    role={words.tone === "muted" ? "status" : "alert"}
                    data-testid="connect-message"
                  >
                    {words.text}
                  </span>
                )}
              </span>
              <span
                className={cn("text-xs", STATUS_CLASS[row.status])}
                data-testid="integration-status"
              >
                {statusLine(row, ago)}
              </span>
              {inline && attempt?.phase === "waiting" ? (
                <button
                  type="button"
                  className={LINK_BUTTON}
                  onClick={() => cancel(row.id)}
                >
                  Cancel
                  <span className="sr-only"> signing in to {row.name}</span>
                </button>
              ) : inline && !(row.selected && !row.pinned) ? (
                <button
                  type="button"
                  className={LINK_BUTTON}
                  disabled={busy}
                  onClick={() => connect(row)}
                >
                  Connect<span className="sr-only"> {row.name}</span>
                </button>
              ) : action.kind === "link" && !(row.selected && !row.pinned) ? (
                <Link href={MCP_SUITE_HREF} className={LINK_BUTTON}>
                  {action.label}
                  <span className="sr-only"> {row.name} in MCP Suite</span>
                </Link>
              ) : row.pinned ? (
                <span className="text-muted-foreground flex min-w-14 items-center justify-end gap-1 text-xs">
                  <LockIcon className="size-3" aria-hidden /> Always on
                </span>
              ) : (
                <span className="flex min-w-14 items-center justify-end">
                  <PickerSwitch
                    checked={row.selected}
                    disabled={!row.selected && overCap}
                    aria-label={`Use ${row.name} in this chat${action.kind === "switch" && action.unverified ? " (not verified working)" : ""}`}
                    onCheckedChange={(on) => onToggleIntegration(row.id, on)}
                  />
                </span>
              )}
            </Row>
          );
        })}
        {!integrationsLoading &&
          filtered.length === 0 &&
          !integrationsError && (
            <li>
              <Empty>
                {query
                  ? `No integration matches "${query}".`
                  : "No integrations configured."}
              </Empty>
            </li>
          )}
      </ul>
    </>
  );
}

function SkillsTab({
  skills,
  skillsError,
  threadAgent,
  excludedSkills = [],
  chatSkillsError,
  onToggleSkill,
}: PickerProps) {
  const { query, setQuery, filtered } = useFilter(skills, skillText);
  const removed = new Set(excludedSkills);
  return (
    <>
      <SearchBox label="Search skills" value={query} onChange={setQuery} />
      <p className="text-muted-foreground px-4 pb-1 text-xs">
        The skills {threadAgent} may use. Turning one off removes it from this
        chat only.
      </p>
      {skillsError ? <Problem>Skills could not be loaded.</Problem> : null}
      {chatSkillsError ? (
        <Problem>
          Which skills this chat removed could not be read, so they cannot be
          changed here.
        </Problem>
      ) : null}
      <ul className="flex flex-col px-1.5 pb-1.5" aria-label="Skills">
        {filtered.map((s) => (
          <Row key={s.name}>
            <span className="min-w-0 flex-1">
              <span className="block truncate">{s.name}</span>
              {s.description && (
                <span className="text-muted-foreground block truncate text-xs">
                  {s.description}
                </span>
              )}
            </span>
            {onToggleSkill && !chatSkillsError && (
              <PickerSwitch
                checked={!removed.has(s.name)}
                aria-label={`Use skill ${s.name} in this chat`}
                onCheckedChange={(on) => onToggleSkill(s.name, on)}
              />
            )}
          </Row>
        ))}
        {!skillsError && skills.length === 0 && (
          <li>
            <Empty>No skills are available to this agent.</Empty>
          </li>
        )}
      </ul>
    </>
  );
}

function FilesTab({
  files,
  uploaded,
  onAttachFiles,
  onRemoveFile,
}: PickerProps) {
  return (
    <div className="flex flex-col gap-2 p-3">
      <Button variant="outline" className="self-start" onClick={onAttachFiles}>
        <PaperclipIcon aria-hidden /> Attach files
      </Button>
      <h3 className="text-muted-foreground px-1 text-xs">With this message</h3>
      <ul className="flex flex-col" aria-label="Files with this message">
        {files.map((f) => (
          <Row key={f.id}>
            <span className="flex-1 truncate">
              {f.filename?.trim() ? f.filename : "Attachment"}
            </span>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onRemoveFile(f.id)}
            >
              Remove<span className="sr-only"> {f.filename}</span>
            </Button>
          </Row>
        ))}
        {files.length === 0 && (
          <li>
            <Empty>No files attached to this message.</Empty>
          </li>
        )}
      </ul>
      {uploaded.length > 0 && (
        <>
          <h3 className="text-muted-foreground px-1 text-xs">
            Already in this chat
          </h3>
          <ul className="flex flex-col" aria-label="Files already in this chat">
            {uploaded.map((f) => (
              <Row key={f.filename}>
                <span className="text-foreground-2 flex-1 truncate font-mono text-xs">
                  {f.filename}
                </span>
              </Row>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
