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
import { fetch as apiFetch } from "@/core/api/fetcher";
import {
  disconnectComposioToolkit,
  getComposioCatalog,
  getComposioConnectionStatus,
  initiateComposioConnection,
  listComposioConnections,
} from "@/core/mcp/api";
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
      return "bg-blue-50 text-blue-700 border-blue-200";
    case "python":
      return "bg-yellow-50 text-yellow-700 border-yellow-200";
    default:
      return "bg-stone-50 text-stone-600 border-stone-200";
  }
}

// ── Status helpers ────────────────────────────────────────────────────────────

function statusBadgeClass(status: McpStatus | string) {
  switch (status) {
    case "deployed":
      return "border-emerald-200 bg-emerald-50 text-emerald-700";
    case "starting":
      return "border-amber-200 bg-amber-50 text-amber-700";
    case "failed":
      return "border-red-200 bg-red-50 text-red-700";
    default:
      return "border-purple-200 bg-purple-50 text-purple-700";
  }
}

function statusDot(status: McpStatus | string) {
  switch (status) {
    case "deployed":
      return "bg-emerald-500";
    case "starting":
      return "bg-amber-400";
    case "failed":
      return "bg-red-500";
    default:
      return "bg-purple-400";
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
        <h2 className="text-sm font-semibold text-stone-700">
          Agent-Built Servers
        </h2>
        {/* Filters */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <SearchIcon className="absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-stone-400" />
            <input
              type="text"
              placeholder="Search your MCPs..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg border border-stone-200 bg-white py-2 pr-3 pl-9 text-sm text-stone-900 placeholder:text-stone-400 focus:border-stone-400 focus:outline-none"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) =>
              setStatusFilter(e.target.value as McpStatus | "all")
            }
            className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm text-stone-700 focus:border-stone-400 focus:outline-none"
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
        <div className="overflow-hidden rounded-xl border border-stone-200 bg-white">
          <table className="w-full">
            <thead>
              <tr className="border-b border-stone-100 bg-stone-50/60">
                <th className="px-5 py-3 text-left text-xs font-medium tracking-wide text-stone-500">
                  Name &amp; Description
                </th>
                <th className="px-5 py-3 text-left text-xs font-medium tracking-wide text-stone-500">
                  Status
                </th>
                <th className="hidden px-5 py-3 text-left text-xs font-medium tracking-wide text-stone-500 md:table-cell">
                  Created
                </th>
                <th className="hidden px-5 py-3 text-left text-xs font-medium tracking-wide text-stone-500 lg:table-cell">
                  Updated
                </th>
                <th className="px-5 py-3 text-right text-xs font-medium tracking-wide text-stone-500">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {loading ? (
                <tr>
                  <td
                    colSpan={5}
                    className="px-5 py-12 text-center text-sm text-stone-400"
                  >
                    Loading…
                  </td>
                </tr>
              ) : error ? (
                <tr>
                  <td
                    colSpan={5}
                    className="px-5 py-12 text-center text-sm text-red-400"
                  >
                    {error}
                  </td>
                </tr>
              ) : servers.length === 0 ? (
                <tr>
                  <td
                    colSpan={5}
                    className="px-5 py-12 text-center text-sm text-stone-400"
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
                    className="group cursor-pointer hover:bg-stone-50/60"
                    onClick={() => router.push(`/workspace/mcp/${mcp.id}`)}
                  >
                    <td className="px-5 py-4">
                      <div className="flex flex-col gap-1.5">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-stone-900">
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
                          <p className="max-w-xs text-xs leading-relaxed text-stone-500">
                            {mcp.description}
                          </p>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <StatusBadge status={mcp.status} />
                    </td>
                    <td className="hidden px-5 py-4 text-sm text-stone-500 md:table-cell">
                      {formatDate(mcp.created_at)}
                    </td>
                    <td className="hidden px-5 py-4 text-sm text-stone-500 lg:table-cell">
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
                            className="rounded p-1.5 text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-700"
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
                              className="rounded px-2 py-1 text-[11px] font-medium text-red-600 hover:bg-red-50"
                            >
                              {deletingId === mcp.id ? "…" : "Delete?"}
                            </button>
                            <button
                              title="Cancel"
                              onClick={() => setConfirmDeleteId(null)}
                              className="rounded p-1.5 text-stone-400 hover:bg-stone-100"
                            >
                              ✕
                            </button>
                          </div>
                        ) : (
                          <button
                            title="Delete"
                            onClick={() => setConfirmDeleteId(mcp.id)}
                            className="rounded p-1.5 text-stone-400 transition-colors hover:bg-red-50 hover:text-red-500"
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
      <h2 className="text-sm font-semibold text-stone-700">
        Connected Toolkits
      </h2>
      <div className="flex flex-wrap gap-3">
        {connections.map((conn) => (
          <div
            key={conn.toolkit}
            className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3"
          >
            <div className="flex size-8 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
              {conn.status === "connected" ? (
                <CheckCircle2Icon className="size-4" />
              ) : (
                <Loader2Icon className="size-4 animate-spin" />
              )}
            </div>
            <div className="flex flex-col">
              <span className="text-sm font-medium text-stone-900">
                {conn.toolkit}
              </span>
              <span className="text-xs text-stone-500">
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

function ConnectionsTab() {
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
        const callbackUrl = `${window.location.origin}/workspace/mcp/callback?toolkit=${toolkit}`;
        const result = await initiateComposioConnection(toolkit, callbackUrl);

        if ("status" in result && result.status === "already_connected") {
          await refreshCatalog();
          return;
        }

        // Mark as pending locally for immediate feedback.
        setToolkits((prev) =>
          prev.map((t) =>
            t.slug === toolkit ? { ...t, status: "pending" } : t,
          ),
        );

        const popup = window.open(
          (result as { composio_redirect_url: string }).composio_redirect_url,
          "composio_oauth",
          "width=600,height=700",
        );

        // connect.composio.dev sends Cross-Origin-Opener-Policy headers that
        // sever the opener-popup link, making popup.closed inaccessible.
        // Poll our own API instead — it auto-syncs from Composio when pending.
        const poll = {
          timer: undefined as ReturnType<typeof setInterval> | undefined,
        };

        const handler = (ev: MessageEvent) => {
          const data = ev.data as { type?: string; toolkit?: string } | null;
          if (
            data?.type === "composio_connected" &&
            data?.toolkit === toolkit
          ) {
            clearInterval(poll.timer);
            window.removeEventListener("message", handler);
            popup?.close();
            void refreshCatalog();
          }
        };
        window.addEventListener("message", handler);

        let pollAttempts = 0;
        poll.timer = setInterval(() => {
          pollAttempts++;
          void (async () => {
            try {
              const status = await getComposioConnectionStatus(toolkit);
              if (status.status === "active" || status.status === "connected") {
                clearInterval(poll.timer);
                window.removeEventListener("message", handler);
                popup?.close();
                void refreshCatalog();
                return;
              }
            } catch {
              /* retry on transient error */
            }
            if (pollAttempts >= 40) {
              clearInterval(poll.timer);
              window.removeEventListener("message", handler);
            }
          })();
        }, 2000);
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
      <p className="text-sm text-stone-500">
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
                ? "border-stone-900 bg-stone-900 text-white"
                : "border-stone-200 bg-white text-stone-600 hover:border-stone-300 hover:bg-stone-50",
            )}
          >
            {cat}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-xs text-red-600">
          {error}
        </div>
      )}

      {loading ? (
        <div className="py-12 text-center text-sm text-stone-400">
          Loading connectors…
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((tk) => (
            <div
              key={tk.slug}
              className="group flex flex-col gap-3 rounded-xl border border-stone-200 bg-white p-5 transition-shadow hover:shadow-md hover:shadow-stone-100"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex size-10 items-center justify-center rounded-xl border border-stone-100 bg-stone-50 text-xl">
                    {tk.icon}
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-stone-900">
                      {tk.name}
                    </p>
                    {tk.status === "connected" && tk.account_display && (
                      <p className="text-[11px] text-stone-400">
                        {tk.account_display}
                      </p>
                    )}
                  </div>
                </div>
                <span className="rounded-full border border-stone-100 bg-stone-50 px-2 py-0.5 text-[10px] text-stone-500">
                  {tk.category}
                </span>
              </div>

              <p className="text-xs leading-relaxed text-stone-500">
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
                        className="rounded-lg border border-stone-200 px-2 py-1 text-xs text-stone-500 hover:bg-stone-50"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <div className="flex flex-1 items-center gap-2">
                      <span className="flex flex-1 items-center gap-1.5 text-xs font-medium text-emerald-600">
                        <CheckCircle2Icon className="size-3.5" />
                        Connected
                      </span>
                      <button
                        onClick={() => setConfirmDisconnect(tk.slug)}
                        className="rounded-lg border border-stone-200 px-2.5 py-1 text-xs text-stone-500 hover:bg-red-50 hover:text-red-500"
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
      <div className="flex items-center justify-between border-b border-stone-200 px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold text-stone-900">MCP Suite</h1>
          <p className="mt-0.5 text-sm text-stone-500">
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
      <div className="flex items-stretch border-b border-stone-100 bg-white">
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
              i !== 2 && "border-r border-stone-100",
            )}
          >
            <div className="flex size-8 items-center justify-center rounded-lg bg-stone-100">
              <Icon className="size-4 text-stone-700" />
            </div>
            <div>
              <p className="text-base font-bold text-stone-900">{value}</p>
              <p className="text-xs text-stone-400">{label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Tab bar */}
      <div className="flex items-center gap-1 border-b border-stone-200 bg-white px-6 pt-4">
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
                ? "border-b-2 border-stone-900 text-stone-900"
                : "text-stone-500 hover:text-stone-700",
            )}
          >
            <Icon className="size-3.5" />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto bg-stone-50/40 p-6">
        {tab === "mine" ? <MyMcpsTab /> : <ConnectionsTab />}
      </div>
    </div>
  );
}
