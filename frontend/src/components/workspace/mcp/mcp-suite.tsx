"use client";

import {
  BoxIcon,
  CheckCircle2Icon,
  CopyIcon,
  EditIcon,
  Globe2Icon,
  Loader2Icon,
  PackageIcon,
  PlugIcon,
  PlusIcon,
  RotateCwIcon,
  SearchIcon,
  Share2Icon,
  Trash2Icon,
  ZapIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { IntegrationIcon } from "@/components/workspace/tools/integration-icon";
import { fetch as apiFetch } from "@/core/api/fetcher";
import {
  disconnectComposioToolkit,
  getComposioCatalog,
  listComposioConnections,
} from "@/core/mcp/api";
import { connectComposioToolkit } from "@/core/mcp/connect";
import {
  type ComposioConnection,
  type ComposioToolkit,
} from "@/core/mcp/types";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type McpStatus = "deployed" | "starting" | "failed" | "stopped" | "not_running";

type MyMcp = {
  id: string;
  name: string;
  description: string | null;
  language: string | null;
  status: McpStatus;
  detected_secrets: string[];
  created_at: string;
  updated_at: string;
};

// ── Language tag color helper ─────────────────────────────────────────────────

function langTagClass(language: string | null): string {
  switch ((language ?? "").toLowerCase()) {
    case "typescript":
      return "bg-highlight/10 text-highlight border-highlight/30";
    case "python":
      // Amber, as Python's tag always was: the warning token is the theme's
      // amber, not a statement that something is wrong.
      return "bg-warning/10 text-warning border-warning/30";
    default:
      return "bg-muted text-muted-foreground border-border";
  }
}

// ── Status helpers ────────────────────────────────────────────────────────────

function statusBadgeClass(status: McpStatus | string) {
  switch (status) {
    case "deployed":
      return "border-success/30 bg-success/10 text-success";
    case "starting":
      return "border-warning/30 bg-warning/10 text-warning";
    case "failed":
      return "border-destructive/30 bg-destructive/10 text-destructive";
    default:
      // Stopped or not running: a neutral state, shown neutrally.
      return "border-border bg-muted text-muted-foreground";
  }
}

function statusDot(status: McpStatus | string) {
  switch (status) {
    case "deployed":
      return "bg-success";
    case "starting":
      return "bg-warning";
    case "failed":
      return "bg-destructive";
    default:
      return "bg-muted-foreground";
  }
}

function statusLabel(status: McpStatus | string): string {
  if (status === "not_running") return "Not running";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: McpStatus | string }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1.5 rounded-full text-[11px]",
        statusBadgeClass(status),
      )}
    >
      <span
        className={cn("inline-block size-1.5 rounded-full", statusDot(status))}
      />
      {statusLabel(status)}
    </Badge>
  );
}

// ── My MCPs tab ───────────────────────────────────────────────────────────────

function MyMcpsTab() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<McpStatus | "all">("all");
  const [servers, setServers] = useState<MyMcp[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);

    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (statusFilter !== "all") params.set("status", statusFilter);

    fetch(`/api/mcp-studio/servers?${params.toString()}`, {
      credentials: "include",
    })
      .then(async (res) => {
        if (!res.ok) {
          if (res.status === 503) {
            setServers([]);
            return;
          }
          throw new Error(`${res.status} ${res.statusText}`);
        }
        const data = (await res.json()) as { servers: MyMcp[]; total: number };
        setServers(data.servers);
      })
      .catch((err: unknown) => {
        setError(
          err instanceof Error ? err.message : "Failed to load MCP servers",
        );
      })
      .finally(() => setLoading(false));
  }, [search, statusFilter]);

  const handleDelete = async (id: string) => {
    setDeletingId(id);
    setConfirmDeleteId(null);
    try {
      const res = await apiFetch(`/api/mcp-studio/servers/${id}`, {
        method: "DELETE",
      });
      if (res.ok || res.status === 204) {
        setServers((prev) => prev.filter((s) => s.id !== id));
      }
    } catch {
      // silently ignore — server might be unreachable
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Connected toolkits (1-click connections) */}
      <ConnectedToolkitsSection />

      {/* Agent-built servers heading */}
      <div className="flex flex-col gap-4">
        <h2 className="text-foreground text-sm font-semibold">
          Agent-Built Servers
        </h2>
        {/* Filters */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <SearchIcon className="text-muted-foreground absolute top-1/2 left-3 size-3.5 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search your MCPs..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="border-border bg-card text-foreground placeholder:text-muted-foreground focus:border-input w-full rounded-lg border py-2 pr-3 pl-9 text-sm focus:outline-none"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) =>
              setStatusFilter(e.target.value as McpStatus | "all")
            }
            className="border-border bg-card text-foreground focus:border-input rounded-lg border px-3 py-2 text-sm focus:outline-none"
          >
            <option value="all">All Statuses</option>
            <option value="deployed">Deployed</option>
            <option value="starting">Starting</option>
            <option value="failed">Failed</option>
            <option value="stopped">Stopped</option>
            <option value="not_running">Not Running</option>
          </select>
        </div>

        {/* Table */}
        <div className="border-border bg-card overflow-hidden rounded-xl border">
          <table className="w-full">
            <thead>
              <tr className="border-border bg-muted/60 border-b">
                <th className="text-muted-foreground px-5 py-3 text-left text-xs font-medium tracking-wide">
                  Name &amp; Description
                </th>
                <th className="text-muted-foreground px-5 py-3 text-left text-xs font-medium tracking-wide">
                  Status
                </th>
                <th className="text-muted-foreground hidden px-5 py-3 text-left text-xs font-medium tracking-wide md:table-cell">
                  Created
                </th>
                <th className="text-muted-foreground hidden px-5 py-3 text-left text-xs font-medium tracking-wide lg:table-cell">
                  Updated
                </th>
                <th className="text-muted-foreground px-5 py-3 text-right text-xs font-medium tracking-wide">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-border divide-y">
              {loading ? (
                <tr>
                  <td
                    colSpan={5}
                    className="text-muted-foreground px-5 py-12 text-center text-sm"
                  >
                    Loading…
                  </td>
                </tr>
              ) : error ? (
                <tr>
                  <td
                    colSpan={5}
                    className="text-destructive px-5 py-12 text-center text-sm"
                  >
                    {error}
                  </td>
                </tr>
              ) : servers.length === 0 ? (
                <tr>
                  <td
                    colSpan={5}
                    className="text-muted-foreground px-5 py-12 text-center text-sm"
                  >
                    {search || statusFilter !== "all"
                      ? "No MCPs match your search."
                      : "No MCP servers yet. Create one to get started."}
                  </td>
                </tr>
              ) : (
                servers.map((mcp) => (
                  <tr
                    key={mcp.id}
                    className="group hover:bg-muted/60 cursor-pointer"
                    onClick={() => router.push(`/workspace/mcp/${mcp.id}`)}
                  >
                    <td className="px-5 py-4">
                      <div className="flex flex-col gap-1.5">
                        <div className="flex items-center gap-2">
                          <span className="text-foreground text-sm font-medium">
                            {mcp.name}
                          </span>
                          {mcp.language && (
                            <span
                              className={cn(
                                "rounded border px-1.5 py-0.5 text-[10px] font-medium",
                                langTagClass(mcp.language),
                              )}
                            >
                              {mcp.language}
                            </span>
                          )}
                        </div>
                        {mcp.description && (
                          <p className="text-muted-foreground max-w-xs text-xs leading-relaxed">
                            {mcp.description}
                          </p>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <StatusBadge status={mcp.status} />
                    </td>
                    <td className="text-muted-foreground hidden px-5 py-4 text-sm md:table-cell">
                      {formatDate(mcp.created_at)}
                    </td>
                    <td className="text-muted-foreground hidden px-5 py-4 text-sm lg:table-cell">
                      {formatDate(mcp.updated_at)}
                    </td>
                    <td
                      className="px-5 py-4"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="flex items-center justify-end gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                        {(
                          [
                            { icon: EditIcon, label: "Edit" },
                            { icon: CopyIcon, label: "Duplicate" },
                            { icon: Share2Icon, label: "Share" },
                          ] as Array<{ icon: React.ElementType; label: string }>
                        ).map(({ icon: Icon, label }) => (
                          <button
                            key={label}
                            title={label}
                            className="text-muted-foreground hover:bg-muted hover:text-foreground rounded p-1.5 transition-colors"
                          >
                            <Icon className="size-3.5" />
                          </button>
                        ))}
                        {confirmDeleteId === mcp.id ? (
                          <div className="flex items-center gap-1">
                            <button
                              title="Confirm delete"
                              onClick={() => void handleDelete(mcp.id)}
                              disabled={deletingId === mcp.id}
                              className="text-destructive hover:bg-destructive/10 rounded px-2 py-1 text-[11px] font-medium"
                            >
                              {deletingId === mcp.id ? "…" : "Delete?"}
                            </button>
                            <button
                              title="Cancel"
                              onClick={() => setConfirmDeleteId(null)}
                              className="text-muted-foreground hover:bg-muted rounded p-1.5"
                            >
                              ✕
                            </button>
                          </div>
                        ) : (
                          <button
                            title="Delete"
                            onClick={() => setConfirmDeleteId(mcp.id)}
                            className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive rounded p-1.5 transition-colors"
                          >
                            <Trash2Icon className="size-3.5" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Connected toolkits section (used inside My MCPs) ──────────────────────────

function ConnectedToolkitsSection() {
  const [connections, setConnections] = useState<ComposioConnection[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listComposioConnections();
      setConnections(
        data.filter((c) => c.status === "connected" || c.status === "pending"),
      );
    } catch {
      setConnections([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (loading || connections.length === 0) {
    // Hide the section entirely when there is nothing connected.
    return null;
  }

  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-foreground text-sm font-semibold">
        Connected Toolkits
      </h2>
      <div className="flex flex-wrap gap-3">
        {connections.map((conn) => (
          <div
            key={conn.toolkit}
            className="border-border bg-card flex items-center gap-3 rounded-xl border px-4 py-3"
          >
            <div className="bg-success/10 text-success flex size-8 items-center justify-center rounded-lg">
              {conn.status === "connected" ? (
                <CheckCircle2Icon className="size-4" />
              ) : (
                <Loader2Icon className="size-4 animate-spin" />
              )}
            </div>
            <div className="flex flex-col">
              <span className="text-foreground text-sm font-medium">
                {conn.toolkit}
              </span>
              <span className="text-muted-foreground text-xs">
                {conn.status === "connected"
                  ? (conn.account_display ?? "Connected")
                  : "Connecting…"}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── 1-Click Connections tab ───────────────────────────────────────────────────

const CONNECTION_CATEGORIES = [
  "All",
  "Productivity",
  "Communication",
  "Knowledge",
  "Dev Tools",
  "Project Mgmt",
];

export function AppCatalog() {
  const [toolkits, setToolkits] = useState<ComposioToolkit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState("All");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState<string | null>(
    null,
  );

  const refreshCatalog = useCallback(async () => {
    try {
      const data = await getComposioCatalog();
      setToolkits(data);
      setError(null);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Failed to load connectors",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshCatalog();
  }, [refreshCatalog]);

  const handleConnect = useCallback(
    async (toolkit: string) => {
      setBusy(toolkit);
      try {
        // Mark as pending locally for immediate feedback while OAuth runs;
        // the button is busy only until the popup opens, as before.
        const outcome = connectComposioToolkit(toolkit, () => {
          setBusy(null);
          setToolkits((prev) =>
            prev.map((t) =>
              t.slug === toolkit ? { ...t, status: "pending" } : t,
            ),
          );
        });
        await outcome;
        await refreshCatalog();
      } catch (err: unknown) {
        setError(
          err instanceof Error ? err.message : "Failed to start connection",
        );
        await refreshCatalog();
      } finally {
        setBusy(null);
      }
    },
    [refreshCatalog],
  );

  const handleDisconnect = useCallback(
    async (toolkit: string) => {
      setBusy(toolkit);
      setConfirmDisconnect(null);
      try {
        await disconnectComposioToolkit(toolkit);
        await refreshCatalog();
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Failed to disconnect");
      } finally {
        setBusy(null);
      }
    },
    [refreshCatalog],
  );

  const filtered = toolkits.filter(
    (t) => activeCategory === "All" || t.category === activeCategory,
  );

  return (
    <div className="flex flex-col gap-5">
      <p className="text-muted-foreground text-sm">
        Connect your accounts with one click. OmniHarness uses Composio to
        handle OAuth securely — tools become available to the agent immediately.
      </p>

      {/* Category pills */}
      <div className="flex flex-wrap gap-2">
        {CONNECTION_CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              activeCategory === cat
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-muted-foreground hover:border-input hover:bg-muted",
            )}
          >
            {cat}
          </button>
        ))}
      </div>

      {error && (
        <div className="border-destructive/30 bg-destructive/10 text-destructive rounded-lg border px-4 py-2 text-xs">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-muted-foreground py-12 text-center text-sm">
          Loading connectors…
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((tk) => (
            <div
              key={tk.slug}
              className="group border-border bg-card flex flex-col gap-3 rounded-xl border p-5 transition-shadow hover:shadow-md"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="border-border bg-muted flex size-10 items-center justify-center overflow-hidden rounded-xl border">
                    <IntegrationIcon slug={tk.slug} size={24} label={tk.name} />
                  </div>
                  <div>
                    <p className="text-foreground text-sm font-semibold">
                      {tk.name}
                    </p>
                    {tk.status === "connected" && tk.account_display && (
                      <p className="text-muted-foreground text-[11px]">
                        {tk.account_display}
                      </p>
                    )}
                  </div>
                </div>
                <span className="border-border bg-muted text-muted-foreground rounded-full border px-2 py-0.5 text-[10px]">
                  {tk.category}
                </span>
              </div>

              <p className="text-muted-foreground text-xs leading-relaxed">
                {tk.description}
              </p>

              <div className="mt-auto flex items-center gap-2 pt-1">
                {tk.status === "connected" ? (
                  confirmDisconnect === tk.slug ? (
                    <div className="flex flex-1 items-center gap-2">
                      <Button
                        size="sm"
                        variant="destructive"
                        className="flex-1 text-xs"
                        disabled={busy === tk.slug}
                        onClick={() => void handleDisconnect(tk.slug)}
                      >
                        {busy === tk.slug ? "…" : "Confirm disconnect"}
                      </Button>
                      <button
                        onClick={() => setConfirmDisconnect(null)}
                        className="border-border text-muted-foreground hover:bg-muted rounded-lg border px-2 py-1 text-xs"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <div className="flex flex-1 items-center gap-2">
                      <span className="text-success flex flex-1 items-center gap-1.5 text-xs font-medium">
                        <CheckCircle2Icon className="size-3.5" />
                        Connected
                      </span>
                      <button
                        onClick={() => setConfirmDisconnect(tk.slug)}
                        className="border-border text-muted-foreground hover:bg-destructive/10 hover:text-destructive rounded-lg border px-2.5 py-1 text-xs"
                      >
                        Disconnect
                      </button>
                    </div>
                  )
                ) : tk.status === "pending" ? (
                  <Button size="sm" className="flex-1 text-xs" disabled>
                    <Loader2Icon className="mr-1 size-3 animate-spin" />
                    Connecting…
                  </Button>
                ) : tk.status === "error" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    className="flex-1 text-xs"
                    disabled={busy === tk.slug}
                    onClick={() => void handleConnect(tk.slug)}
                  >
                    <RotateCwIcon className="mr-1 size-3" />
                    Retry
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    className="flex-1 text-xs"
                    disabled={busy === tk.slug}
                    onClick={() => void handleConnect(tk.slug)}
                  >
                    <PlugIcon className="mr-1 size-3" />
                    Connect
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function McpSuite() {
  const [tab, setTab] = useState<"mine" | "connections">("mine");

  return (
    <div className="flex size-full flex-col">
      {/* Page header */}
      <div className="border-border flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-foreground text-xl font-semibold">MCP Suite</h1>
          <p className="text-muted-foreground mt-0.5 text-sm">
            Build, deploy, and connect MCP servers that give the agent new
            capabilities at runtime.
          </p>
        </div>
        <Button asChild>
          <Link href="/workspace/mcp/new">
            <PlusIcon className="size-4" />
            Create MCP
          </Link>
        </Button>
      </div>

      {/* Stats banner */}
      <div className="border-border bg-card flex items-stretch border-b">
        {[
          {
            value: "Agent-built",
            label: "MCP Servers",
            icon: PackageIcon,
          },
          {
            value: "Sandboxed",
            label: "Isolated Execution",
            icon: Globe2Icon,
          },
          {
            value: "1-Click",
            label: "Install & Connect",
            icon: ZapIcon,
          },
        ].map(({ value, label, icon: Icon }, i) => (
          <div
            key={value}
            className={cn(
              "flex flex-1 items-center justify-center gap-3 py-5",
              i !== 2 && "border-border border-r",
            )}
          >
            <div className="bg-muted flex size-8 items-center justify-center rounded-lg">
              <Icon className="text-foreground size-4" />
            </div>
            <div>
              <p className="text-foreground text-base font-bold">{value}</p>
              <p className="text-muted-foreground text-xs">{label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Tab bar */}
      <div className="border-border bg-card flex items-center gap-1 border-b px-6 pt-4">
        {[
          { id: "mine" as const, label: "My MCPs", icon: BoxIcon },
          {
            id: "connections" as const,
            label: "1-Click Connect",
            icon: ZapIcon,
          },
        ].map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={cn(
              "flex items-center gap-2 rounded-t-lg px-4 py-2.5 text-sm font-medium transition-colors",
              tab === id
                ? "border-foreground text-foreground border-b-2"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-3.5" />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="bg-muted/40 flex-1 overflow-y-auto p-6">
        {tab === "mine" ? <MyMcpsTab /> : <AppCatalog />}
      </div>
    </div>
  );
}
