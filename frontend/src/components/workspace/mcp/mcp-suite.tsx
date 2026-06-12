"use client";

import {
  BoxIcon,
  CopyIcon,
  EditIcon,
  ExternalLinkIcon,
  Globe2Icon,
  PackageIcon,
  PlusIcon,
  SearchIcon,
  Share2Icon,
  Trash2Icon,
  ZapIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetch as apiFetch } from "@/core/api/fetcher";
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

type CatalogMcp = {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  tags: string[];
};

// ── Catalog data (static, curated) ────────────────────────────────────────────

const CATALOG: CatalogMcp[] = [
  {
    id: "c1",
    name: "Web Search",
    description:
      "Real-time web search with Brave, Tavily, or Exa as the backend.",
    category: "Research",
    icon: "🌐",
    tags: ["Search", "Research"],
  },
  {
    id: "c2",
    name: "File System",
    description:
      "Read, write, and manage files within a scoped sandbox directory.",
    category: "Storage",
    icon: "📁",
    tags: ["Files", "Storage"],
  },
  {
    id: "c3",
    name: "Linear",
    description:
      "Manage issues, projects, and cycles in your Linear workspace.",
    category: "Project Mgmt",
    icon: "⚡",
    tags: ["Issues", "PM"],
  },
  {
    id: "c4",
    name: "Stripe Payments",
    description:
      "Query customers, invoices, charges, and subscriptions via Stripe.",
    category: "Payments",
    icon: "💳",
    tags: ["Payments", "Finance"],
  },
  {
    id: "c5",
    name: "Jira Cloud",
    description: "Create and update Jira tickets, sprints, and project boards.",
    category: "Project Mgmt",
    icon: "📋",
    tags: ["Issues", "PM"],
  },
  {
    id: "c6",
    name: "AWS S3",
    description:
      "List, upload, and download objects from S3-compatible stores.",
    category: "Cloud",
    icon: "☁️",
    tags: ["Cloud", "Storage"],
  },
  {
    id: "c7",
    name: "Figma",
    description:
      "Inspect frames, components, and design tokens from Figma files.",
    category: "Design",
    icon: "🎨",
    tags: ["Design", "Assets"],
  },
  {
    id: "c8",
    name: "Google Calendar",
    description:
      "Read and create Google Calendar events and availability slots.",
    category: "Productivity",
    icon: "📅",
    tags: ["Calendar", "Productivity"],
  },
  {
    id: "c9",
    name: "Sentry",
    description:
      "Fetch errors, issues, and performance data from Sentry projects.",
    category: "Monitoring",
    icon: "🛡️",
    tags: ["Errors", "Monitoring"],
  },
];

const CATEGORIES = [
  "All",
  "Research",
  "Storage",
  "Project Mgmt",
  "Cloud",
  "Design",
  "Productivity",
  "Monitoring",
  "Payments",
];

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
    <div className="flex flex-col gap-4">
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
          onChange={(e) => setStatusFilter(e.target.value as McpStatus | "all")}
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
  );
}

// ── MCP Catalog tab ───────────────────────────────────────────────────────────

function McpCatalogTab() {
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState("All");

  const filtered = CATALOG.filter((m) => {
    const matchSearch =
      m.name.toLowerCase().includes(search.toLowerCase()) ||
      m.description.toLowerCase().includes(search.toLowerCase());
    const matchCat = activeCategory === "All" || m.category === activeCategory;
    return matchSearch && matchCat;
  });

  return (
    <div className="flex flex-col gap-5">
      {/* Search */}
      <div className="relative">
        <SearchIcon className="absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-stone-400" />
        <input
          type="text"
          placeholder="Search the catalog..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full rounded-lg border border-stone-200 bg-white py-2 pr-3 pl-9 text-sm text-stone-900 placeholder:text-stone-400 focus:border-stone-400 focus:outline-none"
        />
      </div>

      {/* Category pills */}
      <div className="flex flex-wrap gap-2">
        {CATEGORIES.map((cat) => (
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

      {/* Cards grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.map((mcp) => (
          <div
            key={mcp.id}
            className="group flex flex-col gap-3 rounded-xl border border-stone-200 bg-white p-5 transition-shadow hover:shadow-md hover:shadow-stone-100"
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-xl border border-stone-100 bg-stone-50 text-xl">
                  {mcp.icon}
                </div>
                <div>
                  <p className="text-sm font-semibold text-stone-900">
                    {mcp.name}
                  </p>
                </div>
              </div>
              <span className="rounded-full border border-stone-100 bg-stone-50 px-2 py-0.5 text-[10px] text-stone-500">
                {mcp.category}
              </span>
            </div>

            <p className="text-xs leading-relaxed text-stone-500">
              {mcp.description}
            </p>

            <div className="flex items-center gap-1.5">
              {mcp.tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-full bg-stone-100 px-2 py-0.5 text-[10px] text-stone-500"
                >
                  {tag}
                </span>
              ))}
            </div>

            <div className="mt-auto flex items-center gap-2 pt-1">
              <Button size="sm" className="flex-1 text-xs">
                <PlusIcon className="mr-1 size-3" />
                Install
              </Button>
              <button className="rounded-lg border border-stone-200 p-1.5 text-stone-400 hover:bg-stone-50 hover:text-stone-600">
                <ExternalLinkIcon className="size-3.5" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function McpSuite() {
  const [tab, setTab] = useState<"mine" | "catalog">("mine");

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
          { id: "catalog" as const, label: "MCP Catalog", icon: PackageIcon },
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
        {tab === "mine" ? <MyMcpsTab /> : <McpCatalogTab />}
      </div>
    </div>
  );
}
