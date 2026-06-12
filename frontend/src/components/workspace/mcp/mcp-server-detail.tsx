"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { useStream } from "@langchain/langgraph-sdk/react";
import {
  ArrowLeftIcon,
  ArrowUpRightIcon,
  BoxIcon,
  CheckCircle2Icon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  ClipboardIcon,
  EyeIcon,
  EyeOffIcon,
  FileIcon,
  FolderIcon,
  FolderOpenIcon,
  KeyIcon,
  Loader2Icon,
  LockIcon,
  PlayIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SendIcon,
  ShieldAlertIcon,
  ShieldXIcon,
  TerminalIcon,
  XCircleIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { getAPIClient } from "@/core/api";
import { fetch as apiFetch } from "@/core/api/fetcher";
import type { AgentThreadState } from "@/core/threads/types";
import { cn } from "@/lib/utils";

// ── Types ──────────────────────────────────────────────────────────────────────

type McpPhase =
  | "idle"
  | "building"
  | "testing"
  | "verified"
  | "failed"
  | "ready"
  | "stopped";

type McpBuildStatus = {
  server_id: string;
  phase: McpPhase;
  tools_discovered: Array<{ name: string; description: string }>;
  detected_secret_names: string[];
  errors: string[];
  test_results: Array<{
    tool: string;
    ok: boolean;
    output?: string;
    error?: string;
  }>;
  last_verified_at: string | null;
};

type McpServerResponse = {
  id: string;
  name: string;
  language: string | null;
  description: string | null;
  status: string;
  phase: McpPhase;
  approved: boolean;
  detected_secrets: string[];
  egress_hosts: string[];
  source_code: string | null;
  files: Record<string, string> | null;
  created_at: string;
  updated_at: string;
};

type LifecycleTab = "start" | "build" | "deploy" | "connect";
type InspectSubTab = "tools" | "editor";

type FileNode = {
  name: string;
  path: string;
  type: "file" | "dir";
  children?: FileNode[];
};

// ── Constants ──────────────────────────────────────────────────────────────────

const TEMPLATE_TYPES = [
  { id: "api_wrapper", label: "API Wrapper" },
  { id: "database_connector", label: "Database Connector" },
  { id: "custom_tool", label: "Custom Tool" },
] as const;

const TERMINAL_PHASES: McpPhase[] = [
  "verified",
  "testing",
  "failed",
  "ready",
  "stopped",
];

const GENERATING_PHASES: McpPhase[] = ["idle", "building"];

const MAX_POLL = 120;

// ── Phase display ──────────────────────────────────────────────────────────────

type DisplayPhase = McpPhase | "needs_secrets";

function getDisplayPhase(phase: McpPhase, errors: string[]): DisplayPhase {
  if (phase === "failed" && errors[0]?.startsWith("Missing required secrets")) {
    return "needs_secrets";
  }
  return phase;
}

const PHASE_CONFIG: Record<
  DisplayPhase,
  { label: string; pill: string; dotCls: string; spin?: boolean }
> = {
  idle: {
    label: "Draft",
    pill: "border-stone-200 bg-stone-50 text-stone-500",
    dotCls: "bg-stone-400",
  },
  building: {
    label: "Generating…",
    pill: "border-amber-200 bg-amber-50 text-amber-700",
    dotCls: "bg-amber-500",
    spin: true,
  },
  testing: {
    label: "Couldn't verify",
    pill: "border-orange-200 bg-orange-50 text-orange-700",
    dotCls: "bg-orange-500",
  },
  verified: {
    label: "Verified in sandbox",
    pill: "border-emerald-200 bg-emerald-50 text-emerald-700",
    dotCls: "bg-emerald-500",
  },
  ready: {
    label: "Running",
    pill: "border-emerald-200 bg-emerald-50 text-emerald-700",
    dotCls: "bg-emerald-500",
  },
  failed: {
    label: "Blocked by scan",
    pill: "border-red-200 bg-red-50 text-red-700",
    dotCls: "bg-red-500",
  },
  stopped: {
    label: "Stopped",
    pill: "border-stone-200 bg-stone-50 text-stone-500",
    dotCls: "bg-stone-400",
  },
  needs_secrets: {
    label: "Needs secrets",
    pill: "border-amber-200 bg-amber-50 text-amber-700",
    dotCls: "bg-amber-500",
  },
};

function PhasePill({ phase, errors }: { phase: McpPhase; errors?: string[] }) {
  const dp = getDisplayPhase(phase, errors ?? []);
  const cfg = PHASE_CONFIG[dp] ?? PHASE_CONFIG.idle;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        cfg.pill,
      )}
    >
      {cfg.spin ? (
        <Loader2Icon className="size-3 animate-spin" />
      ) : (
        <span className={cn("size-1.5 rounded-full", cfg.dotCls)} />
      )}
      {cfg.label}
    </span>
  );
}

// ── API helpers ────────────────────────────────────────────────────────────────

async function apiGetServer(id: string): Promise<McpServerResponse | null> {
  const r = await apiFetch(`/api/mcp-studio/servers/${id}`);
  return r.ok ? (r.json() as Promise<McpServerResponse>) : null;
}

async function apiGetBuild(id: string): Promise<McpBuildStatus | null> {
  const r = await apiFetch(`/api/mcp-studio/servers/${id}/build`);
  return r.ok ? (r.json() as Promise<McpBuildStatus>) : null;
}

async function apiCreateServer(body: {
  name: string;
  description?: string;
  template_type?: string;
  language?: string;
}): Promise<{ server_id: string; thread_id: string }> {
  const r = await apiFetch("/api/mcp-studio/servers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok)
    throw new Error(`${r.status}: ${await r.text().catch(() => r.statusText)}`);
  return r.json() as Promise<{ server_id: string; thread_id: string }>;
}

async function apiApprove(id: string): Promise<McpServerResponse> {
  const r = await apiFetch(`/api/mcp-studio/servers/${id}/approve`, {
    method: "POST",
  });
  if (!r.ok)
    throw new Error(`${r.status}: ${await r.text().catch(() => r.statusText)}`);
  return r.json() as Promise<McpServerResponse>;
}

async function apiRetest(id: string): Promise<McpBuildStatus> {
  const r = await apiFetch(`/api/mcp-studio/servers/${id}/test`, {
    method: "POST",
  });
  if (!r.ok)
    throw new Error(`${r.status}: ${await r.text().catch(() => r.statusText)}`);
  return r.json() as Promise<McpBuildStatus>;
}

async function apiWriteSecrets(
  id: string,
  secrets: Record<string, string>,
): Promise<{ stored: string[] }> {
  const r = await apiFetch(`/api/mcp-studio/servers/${id}/secrets`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ secrets }),
  });
  if (!r.ok)
    throw new Error(`${r.status}: ${await r.text().catch(() => r.statusText)}`);
  return r.json() as Promise<{ stored: string[] }>;
}

// ── File tree ──────────────────────────────────────────────────────────────────

function buildTree(files: Record<string, string>): FileNode[] {
  const root: FileNode[] = [];
  const dirs: Record<string, FileNode> = {};

  const ensureDir = (path: string): FileNode => {
    if (dirs[path]) return dirs[path];
    const parts = path.split("/");
    const name = parts[parts.length - 1] ?? path;
    const node: FileNode = { name, path, type: "dir", children: [] };
    dirs[path] = node;
    if (parts.length === 1) {
      root.push(node);
    } else {
      const parentPath = parts.slice(0, -1).join("/");
      const parent = ensureDir(parentPath);
      parent.children!.push(node);
    }
    return node;
  };

  for (const filePath of Object.keys(files).sort()) {
    const parts = filePath.split("/");
    const name = parts[parts.length - 1] ?? filePath;
    const node: FileNode = { name, path: filePath, type: "file" };
    if (parts.length === 1) {
      root.push(node);
    } else {
      const parentPath = parts.slice(0, -1).join("/");
      const parent = ensureDir(parentPath);
      parent.children!.push(node);
    }
  }

  return root;
}

function FileTreeNode({
  node,
  selectedPath,
  onSelect,
  depth = 0,
  isEntrypoint,
}: {
  node: FileNode;
  selectedPath: string;
  onSelect: (path: string) => void;
  depth?: number;
  isEntrypoint?: boolean;
}) {
  const [open, setOpen] = useState(true);

  if (node.type === "dir") {
    return (
      <div>
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-sm hover:bg-stone-100"
          style={{ paddingLeft: `${8 + depth * 12}px` }}
        >
          {open ? (
            <FolderOpenIcon className="size-3.5 shrink-0 text-amber-500" />
          ) : (
            <FolderIcon className="size-3.5 shrink-0 text-amber-500" />
          )}
          {open ? (
            <ChevronDownIcon className="size-3 shrink-0 text-stone-400" />
          ) : (
            <ChevronRightIcon className="size-3 shrink-0 text-stone-400" />
          )}
          <span className="truncate text-stone-700">{node.name}</span>
        </button>
        {open &&
          node.children?.map((child) => (
            <FileTreeNode
              key={child.path}
              node={child}
              selectedPath={selectedPath}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))}
      </div>
    );
  }

  const isSelected = selectedPath === node.path;
  return (
    <button
      onClick={() => onSelect(node.path)}
      className={cn(
        "flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-sm",
        isSelected
          ? "bg-stone-800 text-white"
          : "text-stone-600 hover:bg-stone-100",
      )}
      style={{ paddingLeft: `${8 + depth * 12}px` }}
    >
      <FileIcon
        className={cn(
          "size-3.5 shrink-0",
          isSelected ? "text-stone-300" : "text-stone-400",
        )}
      />
      <span className="truncate">{node.name}</span>
      {isEntrypoint && (
        <span
          className={cn(
            "ml-auto rounded px-1 py-0.5 text-[9px] font-medium",
            isSelected
              ? "bg-stone-600 text-stone-200"
              : "bg-stone-100 text-stone-500",
          )}
        >
          entry
        </span>
      )}
    </button>
  );
}

function FileTreePanel({
  files,
  selectedPath,
  onSelect,
}: {
  files: Record<string, string>;
  selectedPath: string;
  onSelect: (p: string) => void;
}) {
  const nodes = buildTree(files);
  const entrypoint = "server.py";
  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-stone-200 px-3 py-2">
        <span className="text-xs font-semibold tracking-wider text-stone-500 uppercase">
          Files ({Object.keys(files).length})
        </span>
      </div>
      <div className="flex-1 overflow-y-auto py-1">
        {nodes.map((node) => (
          <FileTreeNode
            key={node.path}
            node={node}
            selectedPath={selectedPath}
            onSelect={onSelect}
            isEntrypoint={node.path === entrypoint}
          />
        ))}
      </div>
    </div>
  );
}

// ── Code viewer ────────────────────────────────────────────────────────────────

function CodeViewer({ filename, code }: { filename: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const lines = code.split("\n");

  const handleCopy = () => {
    void navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-stone-950">
      {/* tab bar */}
      <div className="flex items-center gap-0 border-b border-stone-800">
        <div className="flex items-center gap-2 border-r border-stone-800 px-3 py-2">
          <span className="text-xs text-stone-300">{filename}</span>
          <span
            className="size-1.5 rounded-full bg-amber-500"
            title="modified"
          />
        </div>
        <button
          onClick={handleCopy}
          className="mr-3 ml-auto flex items-center gap-1 text-xs text-stone-500 hover:text-stone-200"
        >
          {copied ? (
            <CheckIcon className="size-3 text-emerald-400" />
          ) : (
            <ClipboardIcon className="size-3" />
          )}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {/* code */}
      <div className="flex min-h-0 flex-1 overflow-auto">
        {/* line numbers */}
        <div
          className="border-r border-stone-800 py-4 pr-3 pl-4 text-right font-mono text-xs leading-6 text-stone-600 select-none"
          aria-hidden
        >
          {lines.map((_, i) => (
            <div key={i}>{i + 1}</div>
          ))}
        </div>
        {/* code */}
        <pre className="flex-1 overflow-auto py-4 pr-4 pl-4 font-mono text-xs leading-6 text-stone-200">
          <code>{code}</code>
        </pre>
      </div>
    </div>
  );
}

function CodePlaceholder({ phase }: { phase: McpPhase }) {
  const isGenerating = GENERATING_PHASES.includes(phase);
  return (
    <div
      className={cn(
        "flex flex-1 flex-col items-center justify-center gap-3 bg-stone-950",
        isGenerating ? "text-stone-400" : "text-stone-600",
      )}
    >
      {isGenerating ? (
        <Loader2Icon className="size-8 animate-spin text-amber-500" />
      ) : (
        <TerminalIcon className="size-8" />
      )}
      <p className="text-sm">
        {isGenerating ? "Agent is writing your server…" : "No code generated"}
      </p>
    </div>
  );
}

// ── Build stream helpers ──────────────────────────────────────────────────────

type StreamToolCall = {
  id?: string;
  name: string;
  args: Record<string, unknown>;
};

function extractContentText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return (content as Array<{ type?: string; text?: string }>)
      .filter((b) => b.type === "text")
      .map((b) => b.text ?? "")
      .join("")
      .trim();
  }
  return "";
}

function extractThinkingText(msg: Message): string | null {
  const ak = (msg as { additional_kwargs?: Record<string, unknown> })
    .additional_kwargs;
  if (ak) {
    if (typeof ak.reasoning_content === "string" && ak.reasoning_content)
      return ak.reasoning_content;
    if (Array.isArray(ak.thinking_blocks)) {
      const t = (ak.thinking_blocks as Array<{ thinking?: string }>)
        .map((b) => b.thinking ?? "")
        .join("\n")
        .trim();
      if (t) return t;
    }
  }
  if (Array.isArray(msg.content)) {
    const t = (msg.content as Array<{ type?: string; thinking?: string }>)
      .filter((b) => b.type === "thinking")
      .map((b) => b.thinking ?? "")
      .join("\n")
      .trim();
    if (t) return t;
  }
  return null;
}

function toolCallLabel(
  name: string,
  args: Record<string, unknown>,
): { label: string; detail?: string } {
  const asStr = (v: unknown): string => (typeof v === "string" ? v : "");
  const bn = (p: unknown): string => {
    const s = asStr(p);
    return s.split("/").filter(Boolean).pop() ?? (s || "file");
  };
  switch (name) {
    case "write_file":
      return { label: `Writing \`${bn(args.path ?? args.file_path)}\`` };
    case "str_replace":
      return { label: `Editing \`${bn(args.path ?? args.file_path)}\`` };
    case "read_file":
      return { label: `Reading \`${bn(args.path ?? args.file_path)}\`` };
    case "bash": {
      const cmd = asStr(args.command ?? args.cmd)
        .trim()
        .slice(0, 60);
      return { label: "Running command", detail: cmd || undefined };
    }
    case "ls":
      return { label: "Listing files" };
    case "mcp_build":
      return { label: "Building & testing server" };
    case "write_todos":
      return { label: "Updating task list" };
    case "present_files":
      return { label: "Presenting output" };
    case "ask_clarification":
      return { label: "Asking a question" };
    default:
      return { label: name.replace(/_/g, " ") };
  }
}

function toolResultSummary(name: string, content: string): string {
  if (name === "mcp_build") {
    try {
      const p = JSON.parse(content) as {
        phase?: string;
        tools_discovered?: Array<{ name: string }>;
        errors?: string[];
      };
      if (p.tools_discovered?.length)
        return `Discovered ${p.tools_discovered.length} tool${p.tools_discovered.length === 1 ? "" : "s"}`;
      if (p.errors?.length) return `Issue: ${(p.errors[0] ?? "").slice(0, 80)}`;
      if (p.phase === "verified") return "Server verified ✓";
      if (p.phase === "failed") return "Build failed";
    } catch {
      /* ignore */
    }
  }
  const t = content.replace(/\s+/g, " ").trim();
  return t.slice(0, 100) + (t.length > 100 ? "…" : "");
}

// ── BuildActivityFeed ─────────────────────────────────────────────────────────

function BuildActivityFeed({
  messages,
  isLoading,
  onSubmit,
  onBuildUpdated,
}: {
  messages: Message[];
  isLoading: boolean;
  onSubmit: (text: string) => void;
  onBuildUpdated?: () => void;
}) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new messages or loading state change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, isLoading]);

  // Build tool_call_id → {name, resultText} lookup from tool messages
  const toolResults = useMemo(() => {
    const map = new Map<string, { name: string; text: string }>();
    for (const msg of messages) {
      if (msg.type === "tool") {
        const tm = msg as {
          tool_call_id?: string;
          name?: string;
          content?: unknown;
        };
        if (tm.tool_call_id) {
          map.set(tm.tool_call_id, {
            name: tm.name ?? "",
            text: extractContentText(tm.content),
          });
        }
      }
    }
    return map;
  }, [messages]);

  // Filter to displayable messages (skip empty, skip summarization internals)
  const displayMessages = useMemo(() => {
    return messages.filter((msg) => {
      if ((msg as { name?: string }).name === "summary") return false;
      if (msg.type === "tool") return false; // handled via toolResults map
      if (msg.type === "ai") {
        const toolCalls =
          (msg as { tool_calls?: StreamToolCall[] }).tool_calls ?? [];
        const text = extractContentText(msg.content);
        return (
          toolCalls.length > 0 ||
          text.length > 0 ||
          extractThinkingText(msg) !== null
        );
      }
      return true;
    });
  }, [messages]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || isLoading) return;
    setInput("");
    onSubmit(text);
    onBuildUpdated?.();
  }, [input, isLoading, onSubmit, onBuildUpdated]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const hasContent = displayMessages.length > 0;

  return (
    <div className="flex h-full flex-col bg-white">
      {/* activity feed */}
      <div className="flex-1 space-y-2 overflow-y-auto px-4 py-3">
        {!hasContent && isLoading && (
          <div className="flex flex-col items-center gap-2 py-10 text-center">
            <Loader2Icon className="size-6 animate-spin text-amber-500" />
            <p className="text-sm text-stone-500">
              Agent is writing your server…
            </p>
          </div>
        )}
        {!hasContent && !isLoading && (
          <div className="flex flex-col items-center gap-2 py-10 text-center">
            <TerminalIcon className="size-6 text-stone-300" />
            <p className="text-sm text-stone-400">No activity yet.</p>
            <p className="text-xs text-stone-400">
              Ask the agent to add tools, fix errors, or explain what it wrote.
            </p>
          </div>
        )}

        {displayMessages.map((msg, _msgIdx) => {
          const id = (msg as { id?: string }).id ?? `msg-${_msgIdx}`;

          // Human message
          if (msg.type === "human") {
            const text = extractContentText(msg.content);
            if (!text) return null;
            return (
              <div key={id} className="flex justify-end">
                <div className="max-w-[85%] rounded-xl bg-stone-800 px-3 py-2 text-sm leading-relaxed text-white">
                  {text}
                </div>
              </div>
            );
          }

          // AI message: thinking + text + tool calls
          if (msg.type === "ai") {
            const toolCalls =
              (msg as { tool_calls?: StreamToolCall[] }).tool_calls ?? [];
            const text = extractContentText(msg.content);
            const thinking = extractThinkingText(msg);
            return (
              <div key={id} className="space-y-1.5">
                {/* Thinking disclosure */}
                {thinking && (
                  <details className="group">
                    <summary className="flex cursor-pointer list-none items-center gap-1 text-[11px] text-stone-400 select-none hover:text-stone-600">
                      <ChevronRightIcon className="size-3 transition-transform group-open:rotate-90" />
                      Thinking…
                    </summary>
                    <div className="mt-1 ml-4 rounded-lg border border-stone-100 bg-stone-50 px-3 py-2 text-[11px] leading-relaxed whitespace-pre-wrap text-stone-500">
                      {thinking}
                    </div>
                  </details>
                )}
                {/* AI text bubble */}
                {text && (
                  <div className="flex items-start gap-2">
                    <div className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-stone-800 text-[9px] font-bold text-white">
                      AI
                    </div>
                    <div className="max-w-[85%] rounded-xl bg-stone-100 px-3 py-2 text-sm leading-relaxed text-stone-800">
                      {text}
                    </div>
                  </div>
                )}
                {/* Tool call rows */}
                {toolCalls.map((tc) => {
                  const { label, detail } = toolCallLabel(tc.name, tc.args);
                  const result = tc.id ? toolResults.get(tc.id) : undefined;
                  const isDone = !!result;
                  return (
                    <div
                      key={tc.id ?? tc.name}
                      className="flex items-start gap-2 rounded-lg border border-stone-100 bg-stone-50 px-3 py-2"
                    >
                      {isDone ? (
                        <CheckCircle2Icon className="mt-0.5 size-3.5 shrink-0 text-emerald-500" />
                      ) : (
                        <Loader2Icon className="mt-0.5 size-3.5 shrink-0 animate-spin text-amber-500" />
                      )}
                      <div className="min-w-0 flex-1">
                        <span className="text-xs font-medium text-stone-700">
                          {label}
                        </span>
                        {detail && (
                          <span className="ml-2 truncate font-mono text-[10px] text-stone-400">
                            {detail}
                          </span>
                        )}
                        {isDone && result && (
                          <p className="mt-0.5 text-[10px] leading-relaxed text-stone-500">
                            {toolResultSummary(result.name, result.text)}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          }

          return null;
        })}

        {/* "Agent is working" trailing spinner when loading and there are already some messages */}
        {isLoading && hasContent && (
          <div className="flex items-center gap-2 px-3 py-1.5">
            <Loader2Icon className="size-3.5 animate-spin text-amber-500" />
            <span className="text-xs text-stone-400">Working…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* follow-up input */}
      <div className="border-t border-stone-100 p-3">
        <div className="flex items-end gap-2 rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 focus-within:border-stone-400 focus-within:bg-white">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask the agent to fix, extend, or explain…"
            rows={2}
            disabled={isLoading}
            className="flex-1 resize-none bg-transparent text-sm text-stone-800 placeholder:text-stone-400 focus:outline-none disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="mb-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-stone-800 text-white transition-colors hover:bg-stone-700 disabled:opacity-40"
          >
            {isLoading ? (
              <Loader2Icon className="size-3.5 animate-spin" />
            ) : (
              <SendIcon className="size-3.5" />
            )}
          </button>
        </div>
        <p className="mt-1 text-center text-[10px] text-stone-400">
          Enter to send · Shift+Enter for newline
        </p>
      </div>
    </div>
  );
}

// ── Generating view (Image 1 style) ───────────────────────────────────────────

function GeneratingView({
  server,
  buildStatus,
  threadId,
  onBuildUpdated,
}: {
  server: McpServerResponse;
  buildStatus: McpBuildStatus;
  threadId?: string;
  onBuildUpdated: () => void;
}) {
  const files =
    server.files ??
    (server.source_code ? { "server.py": server.source_code } : null);
  const [selectedFile, setSelectedFile] = useState<string>(() =>
    files
      ? Object.keys(files).includes("server.py")
        ? "server.py"
        : (Object.keys(files)[0] ?? "")
      : "",
  );

  // Live stream of the build thread
  const stream = useStream<AgentThreadState>({
    client: getAPIClient(),
    assistantId: "lead_agent",
    threadId: threadId ?? "",
    reconnectOnMount: true,
    fetchStateHistory: threadId ? { limit: 1 } : undefined,
  });

  // Extract the most-recently-seen source_code arg from mcp_build tool calls
  const liveCode = useMemo<string | null>(() => {
    const msgs = stream.messages;
    if (!msgs?.length) return null;
    for (let i = msgs.length - 1; i >= 0; i--) {
      const msg = msgs[i];
      if (!msg) continue;
      if (msg.type === "ai") {
        const toolCalls =
          (msg as { tool_calls?: StreamToolCall[] }).tool_calls ?? [];
        for (const tc of toolCalls) {
          if (
            tc.name === "mcp_build" &&
            typeof tc.args.source_code === "string" &&
            tc.args.source_code
          ) {
            return tc.args.source_code;
          }
        }
      }
    }
    return null;
  }, [stream.messages]);

  const handleSubmit = useCallback(
    (text: string) => {
      void stream.submit({
        messages: [{ role: "user", content: text } as unknown as Message],
      });
    },
    [stream],
  );

  const { tools_discovered, errors } = buildStatus;
  const phase = buildStatus.phase;
  const [toolsExpanded, setToolsExpanded] = useState(false);

  return (
    <div className="flex h-full min-h-0 gap-0 overflow-hidden">
      {/* LEFT: build activity feed */}
      <div className="flex w-[38%] shrink-0 flex-col border-r border-stone-200">
        {threadId ? (
          <BuildActivityFeed
            messages={stream.messages ?? []}
            isLoading={stream.isLoading}
            onSubmit={handleSubmit}
            onBuildUpdated={onBuildUpdated}
          />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-white p-6 text-center">
            <TerminalIcon className="size-8 text-stone-300" />
            <p className="text-sm text-stone-500">No chat session linked.</p>
            <p className="text-xs text-stone-400">
              Create a new server from the Start tab to get an embedded chat.
            </p>
          </div>
        )}
      </div>

      {/* RIGHT: server info + tools + code */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-stone-50">
        {/* server info card */}
        <div className="border-b border-stone-200 bg-white px-5 py-4">
          <div className="flex items-start gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-stone-800 text-white">
              <TerminalIcon className="size-5" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h2 className="truncate text-base font-semibold text-stone-900">
                  {server.name}
                </h2>
                {server.language && (
                  <span className="rounded border border-stone-200 bg-stone-50 px-1.5 py-0.5 text-[10px] text-stone-500">
                    {server.language}
                  </span>
                )}
                {files && (
                  <span className="rounded border border-stone-200 bg-stone-50 px-1.5 py-0.5 text-[10px] text-stone-500">
                    {Object.keys(files).length}{" "}
                    {Object.keys(files).length === 1 ? "file" : "files"}
                  </span>
                )}
              </div>
              {server.description && (
                <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-stone-500">
                  {server.description}
                </p>
              )}
            </div>
            {threadId && (
              <Link
                href={`/workspace/chats/${threadId}`}
                className="flex items-center gap-1 text-xs text-stone-400 hover:text-stone-700"
                target="_blank"
              >
                Chat <ArrowUpRightIcon className="size-3" />
              </Link>
            )}
          </div>
        </div>

        {/* detected tools */}
        {tools_discovered.length > 0 && (
          <div className="border-b border-stone-200 bg-white px-5 py-3">
            <button
              onClick={() => setToolsExpanded((v) => !v)}
              className="flex items-center gap-2 text-xs font-semibold tracking-wider text-stone-500 uppercase hover:text-stone-700"
            >
              <ChevronRightIcon
                className={cn(
                  "size-3 transition-transform",
                  toolsExpanded && "rotate-90",
                )}
              />
              Detected tools ({tools_discovered.length}) — Click to expand
            </button>
            {toolsExpanded && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {tools_discovered.map((t) => (
                  <span
                    key={t.name}
                    className="flex items-center gap-1 rounded border border-stone-200 bg-stone-50 px-2 py-1 font-mono text-xs text-stone-700"
                  >
                    <ChevronRightIcon className="size-3 text-stone-400" />
                    {t.name}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* errors banner */}
        {errors.length > 0 && phase !== "building" && (
          <div className="border-b border-red-200 bg-red-50 px-5 py-2">
            {errors.map((e, i) => (
              <p
                key={i}
                className="flex items-center gap-1.5 text-xs text-red-700"
              >
                <ShieldAlertIcon className="size-3 shrink-0" /> {e}
              </p>
            ))}
          </div>
        )}

        {/* file tree + code editor */}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {files ? (
            <>
              {/* file tree (white) */}
              <div className="w-44 shrink-0 border-r border-stone-200 bg-white">
                <FileTreePanel
                  files={files}
                  selectedPath={selectedFile}
                  onSelect={setSelectedFile}
                />
              </div>
              {/* code editor (dark) */}
              <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
                {files[selectedFile] !== undefined ? (
                  <CodeViewer
                    filename={selectedFile}
                    code={files[selectedFile]}
                  />
                ) : liveCode ? (
                  <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
                    {stream.isLoading && (
                      <div className="absolute top-2 right-3 z-10 flex items-center gap-1 rounded border border-amber-200 bg-amber-900/80 px-2 py-0.5 text-[10px] text-amber-300">
                        <Loader2Icon className="size-2.5 animate-spin" />{" "}
                        streaming…
                      </div>
                    )}
                    <CodeViewer filename="server.py" code={liveCode} />
                  </div>
                ) : (
                  <CodePlaceholder phase={phase} />
                )}
              </div>
            </>
          ) : liveCode ? (
            <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
              {stream.isLoading && (
                <div className="absolute top-2 right-3 z-10 flex items-center gap-1 rounded border border-amber-200 bg-amber-900/80 px-2 py-0.5 text-[10px] text-amber-300">
                  <Loader2Icon className="size-2.5 animate-spin" /> streaming…
                </div>
              )}
              <CodeViewer filename="server.py" code={liveCode} />
            </div>
          ) : (
            <CodePlaceholder phase={phase} />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Secrets panel (inspect sidebar) ───────────────────────────────────────────

function SecretsSection({
  serverId,
  secretNames,
  storedKeys,
  onStored,
  needsRetest,
}: {
  serverId: string;
  secretNames: string[];
  storedKeys: Set<string>;
  onStored: (keys: string[]) => void;
  needsRetest: boolean;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (secretNames.length === 0) return null;

  const hasUnsaved = Object.values(values).some((v) => v.trim());

  const handleSave = async () => {
    const toSave = Object.fromEntries(
      Object.entries(values).filter(([, v]) => v.trim()),
    );
    if (!Object.keys(toSave).length) return;
    setSaving(true);
    setError(null);
    try {
      const result = await apiWriteSecrets(serverId, toSave);
      onStored(result.stored);
      setValues({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-4">
      <div className="flex items-center gap-2 px-4 pb-2">
        <KeyIcon className="size-3.5 text-stone-500" />
        <h3 className="text-sm font-semibold text-stone-800">
          Secrets &amp; Environment
        </h3>
        {secretNames.some((k) => !storedKeys.has(k)) && (
          <span className="ml-auto flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-medium text-red-600">
            <span className="size-1.5 rounded-full bg-red-500" />
            {secretNames.filter((k) => !storedKeys.has(k)).length} required
          </span>
        )}
      </div>
      <div className="space-y-3 px-4 pb-4">
        <p className="text-[11px] leading-relaxed text-stone-500">
          Configure the secrets your MCP server needs. Values are encrypted at
          rest and auto-detected from code.
        </p>
        <p className="flex items-center gap-1 text-[10px] text-stone-400">
          <span className="inline-block size-1.5 rounded-full bg-stone-400" />{" "}
          Detected from code
        </p>
        {secretNames.map((key) => (
          <div
            key={key}
            className="rounded-lg border border-stone-200 bg-white p-3"
          >
            <div className="mb-1.5 flex items-center justify-between">
              <code className="font-mono text-xs font-semibold text-stone-700">
                {key}
              </code>
              {storedKeys.has(key) ? (
                <span className="flex items-center gap-1 text-[10px] font-medium text-emerald-600">
                  <CheckCircle2Icon className="size-3" /> Stored
                </span>
              ) : (
                <span className="text-[10px] text-stone-400">Not set</span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <input
                type={visible[key] ? "text" : "password"}
                autoComplete="new-password"
                placeholder={
                  storedKeys.has(key) ? "•••••••• (update)" : "Enter value…"
                }
                value={values[key] ?? ""}
                onChange={(e) =>
                  setValues((prev) => ({ ...prev, [key]: e.target.value }))
                }
                className="flex-1 rounded border border-stone-200 bg-stone-50 px-2 py-1.5 text-xs text-stone-900 placeholder:text-stone-400 focus:border-stone-400 focus:bg-white focus:outline-none"
              />
              <button
                type="button"
                onClick={() =>
                  setVisible((prev) => ({ ...prev, [key]: !prev[key] }))
                }
                className="rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
                title={visible[key] ? "Hide" : "Show"}
              >
                {visible[key] ? (
                  <EyeOffIcon className="size-3.5" />
                ) : (
                  <EyeIcon className="size-3.5" />
                )}
              </button>
            </div>
          </div>
        ))}

        {error && <p className="text-xs text-red-500">{error}</p>}

        <Button
          size="sm"
          className="w-full"
          disabled={saving || !hasUnsaved}
          onClick={() => void handleSave()}
        >
          {saving ? (
            <>
              <Loader2Icon className="size-3.5 animate-spin" /> Saving…
            </>
          ) : needsRetest ? (
            "Save & Re-test"
          ) : (
            "Save secrets"
          )}
        </Button>
      </div>
    </div>
  );
}

// ── Inspect sidebar ────────────────────────────────────────────────────────────

function InspectSidebar({
  server,
  buildStatus,
  storedKeys,
  onStored,
}: {
  server: McpServerResponse;
  buildStatus: McpBuildStatus;
  storedKeys: Set<string>;
  onStored: (keys: string[]) => void;
}) {
  const { phase, errors, detected_secret_names } = buildStatus;
  const dp = getDisplayPhase(phase, errors);
  const needsRetest = dp === "needs_secrets";

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-white">
      {/* server details */}
      <div className="border-b border-stone-100 p-4">
        <h3 className="mb-3 text-xs font-semibold tracking-wider text-stone-500 uppercase">
          Server Details
        </h3>
        <div className="space-y-2">
          <div>
            <label className="text-[10px] font-medium tracking-wider text-stone-500 uppercase">
              Name
            </label>
            <div className="mt-1 rounded border border-stone-200 bg-stone-50 px-2.5 py-2 text-sm text-stone-800">
              {server.name}
            </div>
          </div>
          {server.description && (
            <div>
              <label className="text-[10px] font-medium tracking-wider text-stone-500 uppercase">
                Description
              </label>
              <p className="mt-1 text-xs leading-relaxed text-stone-600">
                {server.description}
              </p>
            </div>
          )}
          <div className="flex items-center gap-2 pt-1">
            {server.language && (
              <span className="rounded border border-stone-200 bg-stone-50 px-1.5 py-0.5 text-[10px] text-stone-500">
                {server.language}
              </span>
            )}
            <span className="text-[10px] text-stone-400">
              {new Date(server.created_at).toLocaleDateString()}
            </span>
          </div>
        </div>
      </div>

      {/* secrets */}
      <div className="border-b border-stone-100">
        <SecretsSection
          serverId={server.id}
          secretNames={detected_secret_names}
          storedKeys={storedKeys}
          onStored={onStored}
          needsRetest={needsRetest}
        />
      </div>

      {/* actions */}
      <div className="space-y-2 p-4">
        <h3 className="mb-3 text-xs font-semibold tracking-wider text-stone-500 uppercase">
          Actions
        </h3>
        <ApproveButton
          serverId={server.id}
          phase={phase}
          errors={errors}
          approved={server.approved}
        />
      </div>
    </div>
  );
}

// ── Approve button ─────────────────────────────────────────────────────────────

function ApproveButton({
  serverId,
  phase,
  errors,
  approved,
}: {
  serverId: string;
  phase: McpPhase;
  errors: string[];
  approved: boolean;
}) {
  const [approving, setApproving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const dp = getDisplayPhase(phase, errors);
  const canApprove = dp === "verified" && !approved;

  const handle = async () => {
    setApproving(true);
    setErr(null);
    try {
      await apiApprove(serverId);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
    } finally {
      setApproving(false);
    }
  };

  return (
    <div className="space-y-1.5">
      <Button
        size="sm"
        className="w-full"
        disabled={!canApprove || approving}
        onClick={canApprove ? () => void handle() : undefined}
      >
        {approving ? (
          <>
            <Loader2Icon className="size-3.5 animate-spin" /> Approving…
          </>
        ) : approved ? (
          <>
            <CheckCircle2Icon className="size-3.5" /> Approved
          </>
        ) : (
          "Approve"
        )}
      </Button>
      {!canApprove && !approved && (
        <p className="text-[10px] text-stone-400">
          Requires <span className="font-medium">Verified in sandbox</span>{" "}
          first.
        </p>
      )}
      {err && <p className="text-xs text-red-500">{err}</p>}

      <button
        disabled
        className="mt-2 flex w-full cursor-not-allowed items-center gap-2 rounded-md border border-dashed border-stone-200 px-3 py-2 text-xs text-stone-400"
      >
        <PlayIcon className="size-3.5 shrink-0" />
        <span>Build &amp; run (Docker)</span>
        <span className="ml-auto rounded bg-stone-100 px-1.5 py-0.5 text-[10px]">
          Phase 4
        </span>
      </button>
    </div>
  );
}

// ── MCP Tools view ─────────────────────────────────────────────────────────────

function ToolCard({
  tool,
  testResult,
  onRetest,
}: {
  tool: { name: string; description: string };
  testResult?: { ok: boolean; output?: string; error?: string };
  onRetest?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-stone-200 bg-white">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <ChevronRightIcon
          className={cn(
            "size-3.5 shrink-0 text-stone-400 transition-transform",
            expanded && "rotate-90",
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <code className="text-sm font-semibold text-stone-900">
              {tool.name}
            </code>
            <span className="rounded border border-stone-200 bg-stone-50 px-1.5 py-0.5 text-[10px] text-stone-500">
              async
            </span>
            {testResult && (
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                  testResult.ok
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-red-50 text-red-600",
                )}
              >
                {testResult.ok ? "pass" : "fail"}
              </span>
            )}
          </div>
          {!expanded && tool.description && (
            <p className="mt-0.5 line-clamp-1 text-xs text-stone-500">
              {tool.description}
            </p>
          )}
        </div>
        {onRetest && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onRetest();
            }}
            className="rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
            title="Re-test"
          >
            <RefreshCwIcon className="size-3.5" />
          </button>
        )}
      </button>
      {expanded && (
        <div className="space-y-2 border-t border-stone-100 px-4 py-3">
          {tool.description && (
            <p className="text-sm leading-relaxed text-stone-600">
              {tool.description}
            </p>
          )}
          {testResult?.error && (
            <div className="rounded bg-red-50 px-3 py-2 font-mono text-xs text-red-600">
              {testResult.error}
            </div>
          )}
          {testResult?.output && (
            <div className="rounded bg-stone-800 px-3 py-2 font-mono text-xs text-stone-200">
              {testResult.output}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ToolsView({
  serverId,
  buildStatus,
  onRetested,
}: {
  serverId: string;
  buildStatus: McpBuildStatus;
  onRetested: (s: McpBuildStatus) => void;
}) {
  const { phase, errors, tools_discovered, test_results } = buildStatus;
  const dp = getDisplayPhase(phase, errors);
  const [retesting, setRetesting] = useState(false);

  const handleRetest = async () => {
    setRetesting(true);
    try {
      const result = await apiRetest(serverId);
      onRetested(result);
    } finally {
      setRetesting(false);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* header */}
      <div className="flex items-center gap-3 border-b border-stone-200 bg-white px-5 py-3">
        <span className="text-sm font-medium text-stone-700">
          {tools_discovered.length} tool
          {tools_discovered.length !== 1 ? "s" : ""} discovered
        </span>
        <div className="ml-auto flex items-center gap-2">
          <span className="rounded-md border border-stone-200 bg-white px-2.5 py-1 text-xs text-stone-500">
            Sandbox
          </span>
          {errors.length > 0 ? (
            <span className="flex items-center gap-1 rounded-md border border-red-200 bg-red-50 px-2.5 py-1 text-xs text-red-600">
              <XCircleIcon className="size-3" /> {errors.length} error
              {errors.length !== 1 ? "s" : ""}
            </span>
          ) : (
            <span className="flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs text-emerald-700">
              <CheckCircle2Icon className="size-3" /> 0 errors
            </span>
          )}
          <button
            onClick={() => void handleRetest()}
            disabled={retesting}
            className="rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
            title="Re-test all"
          >
            <RotateCcwIcon
              className={cn("size-4", retesting && "animate-spin")}
            />
          </button>
        </div>
      </div>

      {/* status banner */}
      {dp === "verified" && (
        <div className="flex items-center gap-2 border-b border-emerald-200 bg-emerald-600 px-5 py-2.5">
          <CheckCircle2Icon className="size-4 text-white" />
          <span className="text-sm font-medium text-white">
            SANDBOX VERIFIED — All tools tested successfully
          </span>
        </div>
      )}
      {dp === "needs_secrets" && (
        <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-500 px-5 py-2.5">
          <KeyIcon className="size-4 text-white" />
          <span className="text-sm font-medium text-white">
            NEEDS SECRETS — Provide API keys in the sidebar and re-test
          </span>
        </div>
      )}
      {dp === "failed" && (
        <div className="flex items-center gap-2 border-b border-red-200 bg-red-600 px-5 py-2.5">
          <ShieldXIcon className="size-4 text-white" />
          <span className="text-sm font-medium text-white">
            BLOCKED BY SECURITY SCAN — See errors below
          </span>
        </div>
      )}
      {dp === "testing" && (
        <div className="flex items-center gap-2 border-b border-orange-200 bg-orange-500 px-5 py-2.5">
          <ShieldAlertIcon className="size-4 text-white" />
          <span className="text-sm font-medium text-white">
            COULDN&apos;T VERIFY — Server started but no tools found
          </span>
        </div>
      )}

      {/* tool list */}
      <div className="flex-1 space-y-2 overflow-y-auto p-4">
        {tools_discovered.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-12 text-center">
            <BoxIcon className="size-8 text-stone-300" />
            <p className="text-sm text-stone-400">No tools discovered yet.</p>
            {dp !== "verified" && (
              <p className="text-xs text-stone-400">
                Run re-test to discover tools.
              </p>
            )}
          </div>
        ) : (
          tools_discovered.map((tool) => (
            <ToolCard
              key={tool.name}
              tool={tool}
              testResult={test_results.find((r) => r.tool === tool.name)}
            />
          ))
        )}
      </div>
    </div>
  );
}

// ── Editor view ────────────────────────────────────────────────────────────────

function EditorView({ server }: { server: McpServerResponse }) {
  const files =
    server.files ??
    (server.source_code ? { "server.py": server.source_code } : null);
  const [selectedFile, setSelectedFile] = useState<string>(() =>
    files
      ? Object.keys(files).includes("server.py")
        ? "server.py"
        : (Object.keys(files)[0] ?? "")
      : "",
  );

  if (!files) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 bg-stone-950">
        <TerminalIcon className="size-8 text-stone-600" />
        <p className="text-sm text-stone-500">No code available</p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* file tree */}
      <div className="w-48 shrink-0 border-r border-stone-200 bg-white">
        <FileTreePanel
          files={files}
          selectedPath={selectedFile}
          onSelect={setSelectedFile}
        />
      </div>
      {/* code viewer */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {files[selectedFile] !== undefined ? (
          <CodeViewer filename={selectedFile} code={files[selectedFile]} />
        ) : (
          <div className="flex flex-1 items-center justify-center bg-stone-950">
            <p className="text-sm text-stone-500">Select a file</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Inspect view (Image 2/3 style) ────────────────────────────────────────────

function InspectView({
  server,
  buildStatus,
  threadId,
  onRetested,
}: {
  server: McpServerResponse;
  buildStatus: McpBuildStatus;
  threadId?: string;
  onRetested: (s: McpBuildStatus) => void;
}) {
  const [subTab, setSubTab] = useState<InspectSubTab>("tools");
  const [storedKeys, setStoredKeys] = useState<Set<string>>(new Set());

  const handleStored = (keys: string[]) => {
    setStoredKeys((prev) => new Set([...prev, ...keys]));
    // After saving secrets, trigger re-test if needs_secrets
    void apiRetest(server.id)
      .then(onRetested)
      .catch(() => undefined);
  };

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* LEFT: sidebar */}
      <div className="w-72 shrink-0 overflow-y-auto border-r border-stone-200">
        <InspectSidebar
          server={server}
          buildStatus={buildStatus}
          storedKeys={storedKeys}
          onStored={handleStored}
        />
      </div>

      {/* RIGHT: main */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-stone-50">
        {/* sub-tab bar */}
        <div className="flex items-center gap-1 border-b border-stone-200 bg-white px-5 pt-3">
          {[
            { id: "tools" as InspectSubTab, label: "MCP Tools", icon: BoxIcon },
            {
              id: "editor" as InspectSubTab,
              label: "Editor",
              icon: TerminalIcon,
            },
          ].map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setSubTab(id)}
              className={cn(
                "flex items-center gap-1.5 rounded-t-lg px-4 py-2.5 text-sm font-medium transition-colors",
                subTab === id
                  ? "border-b-2 border-stone-900 text-stone-900"
                  : "text-stone-500 hover:text-stone-700",
              )}
            >
              <Icon className="size-3.5" />
              {label}
            </button>
          ))}
          {threadId && (
            <Link
              href={`/workspace/chats/${threadId}`}
              className="mb-1 ml-auto flex items-center gap-1 rounded border border-stone-200 bg-white px-3 py-1.5 text-xs text-stone-600 hover:bg-stone-50"
            >
              Open chat <ArrowUpRightIcon className="size-3" />
            </Link>
          )}
        </div>

        {/* content */}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {subTab === "tools" && (
            <ToolsView
              serverId={server.id}
              buildStatus={buildStatus}
              onRetested={onRetested}
            />
          )}
          {subTab === "editor" && <EditorView server={server} />}
        </div>
      </div>
    </div>
  );
}

// ── Start tab ──────────────────────────────────────────────────────────────────

function StartTab({
  onCreated,
}: {
  onCreated: (id: string, threadId: string) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [template, setTemplate] = useState("custom_tool");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const doCreate = async () => {
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const { server_id, thread_id } = await apiCreateServer({
        name: name.trim(),
        description: description.trim() || undefined,
        template_type: template,
      });
      onCreated(server_id, thread_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create");
      setCreating(false);
    }
  };

  return (
    <div className="flex flex-1 items-center justify-center bg-stone-50 p-8">
      <div className="w-full max-w-xl space-y-6">
        <div className="space-y-1 text-center">
          <h2 className="text-2xl font-semibold text-stone-900">
            What do you want to build?
          </h2>
          <p className="text-sm text-stone-500">
            Describe your MCP server and the agent will write and verify it.
          </p>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-stone-600">
            Server name <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. GitHub Issues Connector"
            className="w-full rounded-lg border border-stone-200 bg-white px-3 py-2.5 text-sm text-stone-900 placeholder:text-stone-400 focus:border-stone-400 focus:outline-none"
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-stone-600">
            Description
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe what this server should do, what APIs it connects to, and what tools it should expose…"
            rows={4}
            className="w-full resize-none rounded-lg border border-stone-200 bg-white px-3 py-2.5 text-sm text-stone-900 placeholder:text-stone-400 focus:border-stone-400 focus:outline-none"
          />
        </div>

        <div className="space-y-1.5">
          <p className="text-xs font-medium text-stone-600">Template</p>
          <div className="flex flex-wrap gap-2">
            {TEMPLATE_TYPES.map((t) => (
              <button
                key={t.id}
                onClick={() => setTemplate(t.id)}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                  template === t.id
                    ? "border-stone-900 bg-stone-900 text-white"
                    : "border-stone-200 bg-white text-stone-600 hover:border-stone-300 hover:bg-stone-50",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
            {error}
          </p>
        )}

        <Button
          onClick={() => void doCreate()}
          disabled={!name.trim() || creating}
          className="w-full"
        >
          {creating ? (
            <>
              <Loader2Icon className="size-4 animate-spin" /> Creating…
            </>
          ) : (
            "Generate with AI"
          )}
        </Button>
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function McpServerDetail({
  serverId,
  threadId: propThreadId,
}: {
  serverId: string;
  threadId?: string;
}) {
  const router = useRouter();
  const isNew = serverId === "new";

  const [server, setServer] = useState<McpServerResponse | null>(null);
  const [buildStatus, setBuildStatus] = useState<McpBuildStatus | null>(null);
  const [loading, setLoading] = useState(!isNew);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<LifecycleTab>(
    isNew ? "start" : "build",
  );
  const [isPolling, setIsPolling] = useState(false);
  const pollCountRef = useRef(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Initial load
  useEffect(() => {
    if (isNew) return;
    setLoading(true);
    Promise.all([apiGetServer(serverId), apiGetBuild(serverId)])
      .then(([srv, build]) => {
        if (!srv) {
          setLoadError("Server not found");
          return;
        }
        setServer(srv);
        if (build) {
          setBuildStatus(build);
          if (!TERMINAL_PHASES.includes(build.phase)) setIsPolling(true);
        }
      })
      .catch(() => setLoadError("Failed to load server"))
      .finally(() => setLoading(false));
  }, [serverId, isNew]);

  // Poll while generating
  useEffect(() => {
    if (!isPolling) return;
    pollCountRef.current = 0;
    pollRef.current = setInterval(() => {
      pollCountRef.current++;
      if (pollCountRef.current > MAX_POLL) {
        setIsPolling(false);
        return;
      }
      void Promise.all([apiGetServer(serverId), apiGetBuild(serverId)]).then(
        ([srv, build]) => {
          if (srv) setServer(srv);
          if (!build) return;
          setBuildStatus(build);
          if (TERMINAL_PHASES.includes(build.phase)) setIsPolling(false);
        },
      );
    }, 2500);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [isPolling, serverId]);

  const refreshBuild = useCallback(() => {
    void Promise.all([apiGetServer(serverId), apiGetBuild(serverId)]).then(
      ([srv, build]) => {
        if (srv) setServer(srv);
        if (build) setBuildStatus(build);
      },
    );
  }, [serverId]);

  const handleCreated = useCallback(
    (newId: string, newThreadId: string) => {
      router.push(`/workspace/mcp/${newId}?thread=${newThreadId}`);
    },
    [router],
  );

  const handleRetested = useCallback(
    (status: McpBuildStatus) => {
      setBuildStatus(status);
      if (!TERMINAL_PHASES.includes(status.phase)) setIsPolling(true);
      void apiGetServer(serverId).then((srv) => {
        if (srv) setServer(srv);
      });
    },
    [serverId],
  );

  const phase: McpPhase = buildStatus?.phase ?? server?.phase ?? "idle";
  const errors = buildStatus?.errors ?? [];
  const isGenerating = GENERATING_PHASES.includes(phase);

  const LIFECYCLE_TABS: Array<{
    id: LifecycleTab;
    label: string;
    disabled?: boolean;
  }> = [
    { id: "start", label: "Start" },
    { id: "build", label: "Build", disabled: isNew },
    { id: "deploy", label: "Deploy", disabled: true },
    { id: "connect", label: "Connect", disabled: true },
  ];

  if (!isNew && loading) {
    return (
      <div className="flex size-full items-center justify-center">
        <Loader2Icon className="size-6 animate-spin text-stone-400" />
      </div>
    );
  }

  if (!isNew && loadError) {
    return (
      <div className="flex size-full flex-col items-center justify-center gap-3">
        <XCircleIcon className="size-8 text-red-400" />
        <p className="text-sm text-stone-600">{loadError}</p>
        <Link
          href="/workspace/mcp"
          className="text-xs text-stone-500 underline hover:text-stone-700"
        >
          Back to MCP Suite
        </Link>
      </div>
    );
  }

  return (
    <div className="flex size-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-stone-200 bg-white px-5 py-3.5">
        <Link
          href="/workspace/mcp"
          className="rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
        >
          <ArrowLeftIcon className="size-4" />
        </Link>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold tracking-wider text-stone-400 uppercase">
            MCP Studio
          </p>
          <h1 className="truncate text-base font-semibold text-stone-900">
            {isNew ? "New MCP Server" : (server?.name ?? "Loading…")}
          </h1>
        </div>
        {!isNew && <PhasePill phase={phase} errors={errors} />}
        {!isNew && propThreadId && (
          <Link
            href={`/workspace/chats/${propThreadId}`}
            className="flex items-center gap-1.5 rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-xs text-stone-600 hover:bg-stone-50"
          >
            Chat <ArrowUpRightIcon className="size-3.5" />
          </Link>
        )}
      </div>

      {/* Lifecycle tab bar */}
      <div className="flex items-center gap-1 border-b border-stone-200 bg-white px-5 pt-3">
        {LIFECYCLE_TABS.map(({ id, label, disabled }) => (
          <button
            key={id}
            onClick={() => !disabled && setActiveTab(id)}
            disabled={disabled}
            className={cn(
              "flex items-center gap-1.5 rounded-t-lg px-4 py-2.5 text-sm font-medium transition-colors",
              disabled
                ? "cursor-not-allowed text-stone-300"
                : activeTab === id
                  ? "border-b-2 border-stone-900 text-stone-900"
                  : "text-stone-500 hover:text-stone-700",
            )}
          >
            {label}
            {disabled && <LockIcon className="size-3 text-stone-300" />}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {activeTab === "start" && isNew && (
          <StartTab onCreated={handleCreated} />
        )}
        {activeTab === "start" && !isNew && (
          <div className="flex flex-1 items-center justify-center bg-stone-50 p-8">
            <div className="space-y-3 text-center">
              <p className="text-sm text-stone-500">
                This server was already created.
              </p>
              <Button size="sm" onClick={() => setActiveTab("build")}>
                View Build →
              </Button>
            </div>
          </div>
        )}
        {activeTab === "build" &&
          !isNew &&
          server &&
          buildStatus &&
          (isGenerating ? (
            <GeneratingView
              server={server}
              buildStatus={buildStatus}
              threadId={propThreadId}
              onBuildUpdated={refreshBuild}
            />
          ) : (
            <InspectView
              server={server}
              buildStatus={buildStatus}
              threadId={propThreadId}
              onRetested={handleRetested}
            />
          ))}
        {activeTab === "build" &&
          !isNew &&
          (!server || !buildStatus) &&
          !loading && (
            <div className="flex flex-1 items-center justify-center bg-stone-50">
              <p className="text-sm text-stone-400">No build data yet.</p>
            </div>
          )}
        {(activeTab === "deploy" || activeTab === "connect") && (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 bg-stone-50">
            <LockIcon className="size-8 text-stone-300" />
            <p className="text-sm text-stone-400">
              {activeTab === "deploy" ? "Deploy" : "Connect"} is available in
              Phase 4
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
