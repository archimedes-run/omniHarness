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
  ShieldCheckIcon,
  Trash2Icon,
  ZapIcon,
} from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type McpStatus = "deployed" | "starting" | "failed" | "stopped";

type MyMcp = {
  id: string;
  name: string;
  description: string;
  tag: string;
  tagColor: string;
  status: McpStatus;
  createdAt: string;
  updatedAt: string;
  role: "owner" | "member";
};

type CatalogMcp = {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  installs: string;
  tags: string[];
};

// ── Mock data ─────────────────────────────────────────────────────────────────

const MY_MCPS: MyMcp[] = [
  {
    id: "1",
    name: "GitHub Integration",
    description:
      "Full GitHub API access — repos, issues, PRs, actions and more.",
    tag: "TypeScript",
    tagColor: "bg-blue-50 text-blue-700 border-blue-200",
    status: "deployed",
    createdAt: "Jun 4, 2026",
    updatedAt: "Jun 9, 2026",
    role: "owner",
  },
  {
    id: "2",
    name: "Slack Messenger",
    description: "Post messages, read channels, and manage Slack workspaces.",
    tag: "Python",
    tagColor: "bg-yellow-50 text-yellow-700 border-yellow-200",
    status: "deployed",
    createdAt: "May 28, 2026",
    updatedAt: "Jun 8, 2026",
    role: "owner",
  },
  {
    id: "3",
    name: "PostgreSQL Query",
    description:
      "Execute read-only SQL queries against your Postgres database.",
    tag: "Python",
    tagColor: "bg-yellow-50 text-yellow-700 border-yellow-200",
    status: "starting",
    createdAt: "Jun 10, 2026",
    updatedAt: "Jun 10, 2026",
    role: "member",
  },
  {
    id: "4",
    name: "Notion Workspace",
    description: "Read and write Notion pages, databases, and blocks.",
    tag: "TypeScript",
    tagColor: "bg-blue-50 text-blue-700 border-blue-200",
    status: "failed",
    createdAt: "Jun 1, 2026",
    updatedAt: "Jun 5, 2026",
    role: "owner",
  },
];

const CATALOG: CatalogMcp[] = [
  {
    id: "c1",
    name: "Web Search",
    description:
      "Real-time web search with Brave, Tavily, or Exa as the backend.",
    category: "Research",
    icon: "🌐",
    installs: "12k",
    tags: ["Search", "Research"],
  },
  {
    id: "c2",
    name: "File System",
    description:
      "Read, write, and manage files within a scoped sandbox directory.",
    category: "Storage",
    icon: "📁",
    installs: "9.4k",
    tags: ["Files", "Storage"],
  },
  {
    id: "c3",
    name: "Linear",
    description:
      "Manage issues, projects, and cycles in your Linear workspace.",
    category: "Project Mgmt",
    icon: "⚡",
    installs: "7.1k",
    tags: ["Issues", "PM"],
  },
  {
    id: "c4",
    name: "Stripe Payments",
    description:
      "Query customers, invoices, charges, and subscriptions via Stripe.",
    category: "Payments",
    icon: "💳",
    installs: "6.8k",
    tags: ["Payments", "Finance"],
  },
  {
    id: "c5",
    name: "Jira Cloud",
    description: "Create and update Jira tickets, sprints, and project boards.",
    category: "Project Mgmt",
    icon: "📋",
    installs: "5.9k",
    tags: ["Issues", "PM"],
  },
  {
    id: "c6",
    name: "AWS S3",
    description:
      "List, upload, and download objects from S3-compatible stores.",
    category: "Cloud",
    icon: "☁️",
    installs: "5.2k",
    tags: ["Cloud", "Storage"],
  },
  {
    id: "c7",
    name: "Figma",
    description:
      "Inspect frames, components, and design tokens from Figma files.",
    category: "Design",
    icon: "🎨",
    installs: "4.8k",
    tags: ["Design", "Assets"],
  },
  {
    id: "c8",
    name: "Google Calendar",
    description:
      "Read and create Google Calendar events and availability slots.",
    category: "Productivity",
    icon: "📅",
    installs: "4.3k",
    tags: ["Calendar", "Productivity"],
  },
  {
    id: "c9",
    name: "Sentry",
    description:
      "Fetch errors, issues, and performance data from Sentry projects.",
    category: "Monitoring",
    icon: "🛡️",
    installs: "3.7k",
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

// ── Status helpers ────────────────────────────────────────────────────────────

function statusBadgeClass(status: McpStatus | string) {
  switch (status) {
    case "deployed":
      return "border-emerald-200 bg-emerald-50 text-emerald-700";
    case "starting":
      return "border-amber-200 bg-amber-50 text-amber-700";
    case "failed":
      return "border-red-200 bg-red-50 text-red-700";
    case "stopped":
    default:
      return "border-purple-200 bg-purple-50 text-purple-700";
  }
}

function statusDot(status: McpStatus) {
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

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: McpStatus }) {
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
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </Badge>
  );
}

function RoleBadge({ role }: { role: "owner" | "member" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
        role === "owner"
          ? "border-stone-200 bg-stone-50 text-stone-600"
          : "border-blue-100 bg-blue-50 text-blue-600",
      )}
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          role === "owner" ? "bg-stone-400" : "bg-blue-400",
        )}
      />
      {role === "owner" ? "Owner" : "Member"}
    </span>
  );
}

// ── My MCPs tab ───────────────────────────────────────────────────────────────

function MyMcpsTab() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<McpStatus | "all">("all");

  const filtered = MY_MCPS.filter((m) => {
    const matchSearch =
      m.name.toLowerCase().includes(search.toLowerCase()) ||
      m.description.toLowerCase().includes(search.toLowerCase());
    const matchStatus = statusFilter === "all" || m.status === statusFilter;
    return matchSearch && matchStatus;
  });

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
                Created At
              </th>
              <th className="hidden px-5 py-3 text-left text-xs font-medium tracking-wide text-stone-500 lg:table-cell">
                Updated At
              </th>
              <th className="px-5 py-3 text-right text-xs font-medium tracking-wide text-stone-500">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {filtered.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  className="px-5 py-12 text-center text-sm text-stone-400"
                >
                  No MCPs match your search.
                </td>
              </tr>
            ) : (
              filtered.map((mcp) => (
                <tr key={mcp.id} className="group hover:bg-stone-50/60">
                  <td className="px-5 py-4">
                    <div className="flex flex-col gap-1.5">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-stone-900">
                          {mcp.name}
                        </span>
                        <span
                          className={cn(
                            "rounded border px-1.5 py-0.5 text-[10px] font-medium",
                            mcp.tagColor,
                          )}
                        >
                          {mcp.tag}
                        </span>
                      </div>
                      <p className="max-w-xs text-xs leading-relaxed text-stone-500">
                        {mcp.description}
                      </p>
                      <div className="flex items-center gap-1.5 text-[10px] text-stone-400">
                        <span>Created {mcp.createdAt}</span>
                        <RoleBadge role={mcp.role} />
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <StatusBadge status={mcp.status} />
                  </td>
                  <td className="hidden px-5 py-4 text-sm text-stone-500 md:table-cell">
                    {mcp.createdAt}
                  </td>
                  <td className="hidden px-5 py-4 text-sm text-stone-500 lg:table-cell">
                    {mcp.updatedAt}
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex items-center justify-end gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                      {[
                        { icon: EditIcon, label: "Edit" },
                        { icon: CopyIcon, label: "Duplicate" },
                        { icon: Share2Icon, label: "Share" },
                        { icon: Trash2Icon, label: "Delete" },
                      ].map(({ icon: Icon, label }) => (
                        <button
                          key={label}
                          title={label}
                          className={cn(
                            "rounded p-1.5 text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-700",
                            label === "Delete" && "hover:text-red-500",
                          )}
                        >
                          <Icon className="size-3.5" />
                        </button>
                      ))}
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
                  <span className="text-[10px] text-stone-400">
                    {mcp.installs} installs
                  </span>
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
        <Button>
          <PlusIcon className="size-4" />
          Create MCP
        </Button>
      </div>

      {/* Stats banner */}
      <div className="flex items-stretch border-b border-stone-100 bg-white">
        {[
          {
            value: "50+",
            label: "Pre-built Integrations",
            icon: PackageIcon,
          },
          {
            value: "Enterprise",
            label: "Security & Compliance",
            icon: ShieldCheckIcon,
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

      {/* Docker security strip */}
      <div className="flex items-center justify-between border-b border-stone-900 bg-stone-950 px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-blue-500">
            <Globe2Icon className="size-4 text-white" />
          </div>
          <div>
            <p className="text-sm font-medium text-white">Secured by Docker</p>
            <p className="text-xs text-stone-400">
              MCP servers run in isolated containers with scoped permissions
            </p>
          </div>
        </div>
        <div className="hidden items-center gap-2 sm:flex">
          {["SBOMs", "Provenance", "Signed Images", "Learn about MCP"].map(
            (label) => (
              <button
                key={label}
                className="flex items-center gap-1 rounded-md border border-stone-700 px-2.5 py-1 text-xs text-stone-300 transition-colors hover:border-stone-500 hover:text-white"
              >
                {label}
                <ExternalLinkIcon className="size-3" />
              </button>
            ),
          )}
        </div>
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
