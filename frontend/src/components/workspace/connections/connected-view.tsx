"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { SearchIcon, TerminalIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { BrandLogo } from "@/components/brand";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import {
  PageCard,
  RowList,
  SectionHeading,
  StatusWord,
  type StatusTone,
} from "@/components/workspace/page-kit";
import { disconnectComposioToolkit, getComposioCatalog } from "@/core/mcp/api";
import { connectComposioToolkit } from "@/core/mcp/connect";
import { useEnableMCPServer, useMCPConfig } from "@/core/mcp/hooks";
import type { ComposioToolkit } from "@/core/mcp/types";
import { retryToolSources } from "@/core/tool-sources/api";
import { useToolSources } from "@/core/tool-sources/hooks";
import type { ToolSource } from "@/core/tool-sources/types";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

import { BuiltServerRows } from "./built-server-rows";
import { countSources, sourceStatus, transportOf } from "./connected-logic";

/**
 * MCP Suite > Connected (Feature 006 board "Connections"): the counts, every
 * failing source with its real error and a Retry, the apps as cards with their
 * official logos, and the MCP servers as rows. Feature 004's honesty holds:
 * "can't tell" is never "none", and a failing source is never hidden.
 */
export function ConnectedView() {
  const { view, isLoading, error } = useToolSources();
  const { config } = useMCPConfig();

  if (isLoading) {
    return <p className="text-muted-foreground text-sm">Loading…</p>;
  }
  if (error != null || !view) {
    return (
      <PageCard
        as="section"
        className="border-destructive"
        data-testid="unreadable"
        aria-label="Tool sources unreadable"
      >
        <div className="font-medium">
          I can&apos;t tell which tool sources are working
        </div>
        <p className="text-muted-foreground text-[13px]">
          {error != null ? String(error) : "No answer from the gateway."}
        </p>
      </PageCard>
    );
  }

  const counts = countSources(view.sources);
  const failing = view.sources.filter((s) => s.state === "unreachable");
  const connectors = view.sources.filter((s) => s.kind === "connector");
  const local = view.sources.filter((s) => s.kind === "local");

  return (
    <div className="flex flex-col gap-[22px]">
      <div className="flex flex-wrap gap-2.5" data-testid="source-counts">
        <CountPill n={counts.live} word="live" tone="good" />
        {counts.unreachable > 0 && (
          <CountPill
            n={counts.unreachable}
            word="unreachable"
            tone="warn"
            className="border-warning/40"
          />
        )}
        <CountPill n={counts.notConnected} word="not connected" tone="muted" />
        {counts.off > 0 && <CountPill n={counts.off} word="off" tone="muted" />}
        {counts.unknown > 0 && (
          <CountPill n={counts.unknown} word="can't tell yet" tone="muted" />
        )}
      </div>

      {failing.map((source) => (
        <NeedsAttention key={source.id} source={source} />
      ))}

      <AppsSection
        connectors={connectors}
        available={view.connectors_available}
      />

      <SectionHeading className="mt-2">MCP servers</SectionHeading>
      <RowList data-testid="mcp-servers">
        {local.map((source) => (
          <ServerRow
            key={source.id}
            source={source}
            entry={
              config?.mcp_servers[source.id.slice(source.id.indexOf(":") + 1)]
            }
          />
        ))}
        <BuiltServerRows
          exclude={
            new Set(
              local.map((s) => s.id.slice(s.id.indexOf(":") + 1).toLowerCase()),
            )
          }
        />
      </RowList>
    </div>
  );
}

function CountPill({
  n,
  word,
  tone,
  className,
}: {
  n: number;
  word: string;
  tone: StatusTone;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "bg-card border-border rounded-lg border px-3 py-2",
        className,
      )}
      data-testid={`count-${word.replace(/[^a-z]+/g, "-")}`}
    >
      <strong className="font-semibold">{n}</strong>{" "}
      <StatusWord tone={tone} className="text-sm">
        {word}
      </StatusWord>
    </span>
  );
}

/** One failing source: what it costs, its real error, and Retry. */
function NeedsAttention({ source }: { source: ToolSource }) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const watcher = source.name === "session-watcher";
  const reason = source.error ?? source.last_error ?? null;

  const retry = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const fresh = await retryToolSources();
      queryClient.setQueryData(["toolSources", null], fresh);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      aria-label={`${source.name} needs attention`}
      className="bg-card border-warning flex flex-wrap items-center gap-3.5 rounded-xl border px-[18px] py-3.5"
      data-testid="needs-attention"
      data-source={source.id}
    >
      <span className="bg-surface-raised flex size-8 flex-none items-center justify-center rounded-md">
        <TerminalIcon className="text-foreground-2 size-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-[1_1_320px]">
        <div className="font-medium">{source.name} can&apos;t be reached</div>
        <div className="text-muted-foreground text-[13px]">
          {watcher
            ? "Agents can't see your coding sessions until it's back."
            : "Agents don't have its tools until it's back."}{" "}
          {reason ? (
            <span
              className="font-mono text-xs break-all"
              data-testid="source-error"
            >
              {reason}
            </span>
          ) : (
            <span data-testid="source-error-unknown">
              The gateway did not say why.
            </span>
          )}
          {source.last_failure_at && (
            <span> · last failed {formatTimeAgo(source.last_failure_at)}</span>
          )}
        </div>
        {problem && (
          <p className="text-destructive text-xs" role="alert">
            {problem}
          </p>
        )}
      </div>
      <Button
        className="bg-warning text-warning-foreground hover:bg-warning/90 rounded-lg font-semibold max-md:min-h-11"
        disabled={busy}
        onClick={() => void retry()}
      >
        {busy ? "Retrying…" : "Retry"}
      </Button>
    </section>
  );
}

function AppsSection({
  connectors,
  available,
}: {
  connectors: ToolSource[];
  available: boolean;
}) {
  const [category, setCategory] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  // Descriptions and categories come from the Composio catalog. Unreadable,
  // the cards show without them: never a made-up description.
  const { data: catalog } = useQuery({
    queryKey: ["composioCatalog"],
    queryFn: getComposioCatalog,
    enabled: available,
    staleTime: 5 * 60_000,
    retry: false,
  });
  const bySlug = useMemo(() => {
    const map = new Map<string, ComposioToolkit>();
    for (const tk of catalog ?? []) map.set(tk.slug.toLowerCase(), tk);
    return map;
  }, [catalog]);
  const meta = (s: ToolSource) =>
    bySlug.get(s.id.slice(s.id.indexOf(":") + 1).toLowerCase());
  const categories = [
    ...new Set(
      connectors.map((s) => meta(s)?.category).filter((c): c is string => !!c),
    ),
  ].sort();
  const shown = connectors.filter(
    (s) =>
      (category === null || meta(s)?.category === category) &&
      s.name.toLowerCase().includes(search.trim().toLowerCase()),
  );

  return (
    <section aria-labelledby="apps-heading" className="flex flex-col gap-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <SectionHeading id="apps-heading" className="mr-3">
          Apps
        </SectionHeading>
        {available && categories.length > 0 && (
          <>
            <Chip pressed={category === null} onClick={() => setCategory(null)}>
              All
            </Chip>
            {categories.map((c) => (
              <Chip
                key={c}
                pressed={category === c}
                onClick={() => setCategory(c)}
              >
                {c}
              </Chip>
            ))}
          </>
        )}
        <span className="flex-1" />
        {available && (
          <label className="bg-card border-border-strong flex min-w-[200px] items-center gap-2 rounded-lg border px-2.5 py-1.5">
            <SearchIcon
              className="text-muted-foreground size-3.5"
              aria-hidden
            />
            <span className="sr-only">Search apps</span>
            <input
              type="search"
              placeholder="Search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-sm outline-none"
            />
          </label>
        )}
      </div>
      {available ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-3.5">
          {shown.map((source) => (
            <AppCard
              key={source.id}
              source={source}
              description={meta(source)?.description}
            />
          ))}
          {shown.length === 0 && (
            <p className="text-muted-foreground text-sm">
              No app matches that search.
            </p>
          )}
        </div>
      ) : (
        <p
          className="text-muted-foreground text-sm"
          data-testid="no-connectors"
        >
          Apps are not available: Composio is not configured on this gateway, so
          none can be connected here.
        </p>
      )}
    </section>
  );
}

function Chip({
  pressed,
  onClick,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        "rounded-full px-3 py-1 text-[13px] max-md:min-h-11",
        pressed
          ? "bg-foreground text-background"
          : "border-border-strong text-foreground-2 hover:bg-accent border",
      )}
    >
      {children}
    </button>
  );
}

function AppCard({
  source,
  description,
}: {
  source: ToolSource;
  description: string | undefined;
}) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const slug = source.id.slice(source.id.indexOf(":") + 1);
  const status = sourceStatus(source);
  const connected = source.state !== "not-authorised";

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setProblem(null);
    try {
      await work();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      void queryClient.invalidateQueries({ queryKey: ["toolSources"] });
    }
  };

  return (
    <article
      className={cn(
        "flex flex-col gap-3 rounded-xl border px-[18px] py-4",
        connected
          ? "bg-card border-border"
          : "bg-sidebar border-border-strong border-dashed",
      )}
      data-testid="tool-source"
      data-source={source.id}
      data-state={source.state}
    >
      <div className="flex items-center gap-3">
        <BrandLogo
          source={source.id}
          name={source.name}
          size={36}
          className="rounded-[9px]"
        />
        <div className="min-w-0 flex-1">
          <div className="font-medium">{source.name}</div>
          {description && (
            <div className="text-muted-foreground line-clamp-1 text-xs">
              {description}
            </div>
          )}
        </div>
        {connected && (
          <StatusWord tone={status.tone}>{status.label}</StatusWord>
        )}
      </div>
      {connected ? (
        <div className="border-border flex items-center gap-2.5 border-t pt-2.5">
          <span className="text-foreground-2 flex-1 text-[13px]">
            {status.meaning}
          </span>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`${source.name} options`}
                className="text-muted-foreground max-md:size-11"
              >
                ⋯
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                disabled={busy}
                onSelect={() => void run(() => disconnectComposioToolkit(slug))}
              >
                Disconnect {source.name}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      ) : (
        <Button
          variant="outline"
          className="border-border-strong rounded-lg bg-transparent max-md:min-h-11"
          disabled={busy}
          onClick={() => void run(() => connectComposioToolkit(slug))}
        >
          Connect
        </Button>
      )}
      {problem && (
        <p className="text-destructive text-xs" data-testid="action-error">
          {problem}
        </p>
      )}
    </article>
  );
}

/** One configured MCP server: name, where it runs, tools, status, on/off. */
function ServerRow({
  source,
  entry,
}: {
  source: ToolSource;
  entry: Record<string, unknown> | undefined;
}) {
  const queryClient = useQueryClient();
  const enable = useEnableMCPServer();
  const [problem, setProblem] = useState<string | null>(null);
  const status = sourceStatus(source);
  const name = source.id.slice(source.id.indexOf(":") + 1);
  const on = source.state !== "disabled";

  return (
    <li
      className="flex flex-wrap items-center gap-3.5 px-[18px] py-3"
      data-testid="tool-source"
      data-source={source.id}
      data-state={source.state}
    >
      <span className="min-w-0 flex-[1_1_200px] font-mono text-[13px]">
        {source.name}
        {!entry && (
          <span className="text-muted-foreground ml-2 font-sans text-xs">
            · no entry in your MCP config
          </span>
        )}
      </span>
      <span className="text-muted-foreground w-[110px] text-xs">
        {transportOf(entry)}
      </span>
      <span className="text-muted-foreground w-[70px] text-xs">
        {source.tool_count == null ? "— tools" : `${source.tool_count} tools`}
      </span>
      <StatusWord tone={status.tone} className="w-[90px]">
        {status.label}
      </StatusWord>
      {entry ? (
        <Switch
          checked={on}
          disabled={enable.isPending}
          aria-label={`${on ? "Turn off" : "Turn on"} ${source.name}`}
          onCheckedChange={(next) => {
            setProblem(null);
            enable
              .mutateAsync({ serverName: name, enabled: next })
              .catch((err: unknown) =>
                setProblem(err instanceof Error ? err.message : String(err)),
              )
              .finally(
                () =>
                  void queryClient.invalidateQueries({
                    queryKey: ["toolSources"],
                  }),
              );
          }}
        />
      ) : (
        <span className="w-8" />
      )}
      {problem && (
        <p className="text-destructive basis-full text-xs">{problem}</p>
      )}
    </li>
  );
}
