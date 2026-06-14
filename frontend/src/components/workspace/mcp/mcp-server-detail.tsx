"use client";

import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import { javascript } from "@codemirror/lang-javascript";
import { json } from "@codemirror/lang-json";
import { python } from "@codemirror/lang-python";
import type { Message } from "@langchain/langgraph-sdk";
import { useStream } from "@langchain/langgraph-sdk/react";
import { monokaiInit } from "@uiw/codemirror-theme-monokai";
import CodeMirror from "@uiw/react-codemirror";
import {
  ArrowLeftIcon,
  BoxIcon,
  CheckCircle2Icon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  ClipboardIcon,
  CopyIcon,
  EyeIcon,
  EyeOffIcon,
  FileIcon,
  FolderIcon,
  FolderOpenIcon,
  KeyIcon,
  Loader2Icon,
  LockIcon,
  PlugIcon,
  PlugZapIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SendIcon,
  ShieldAlertIcon,
  ShieldXIcon,
  SparklesIcon,
  SquareIcon,
  TerminalIcon,
  XCircleIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { MessageResponse } from "@/components/ai-elements/message";
import { Button } from "@/components/ui/button";
import { getAPIClient } from "@/core/api";
import { fetch as apiFetch } from "@/core/api/fetcher";
import { streamdownPlugins } from "@/core/streamdown";
import type { AgentThreadState } from "@/core/threads/types";
import { cn } from "@/lib/utils";

// ── CodeMirror dark theme ──────────────────────────────────────────────────────
const cmDarkTheme = monokaiInit({
  settings: {
    background: "#13141a",
    gutterBackground: "#13141a",
    gutterForeground: "#4a5060",
    gutterActiveForeground: "#9CA3AF",
    gutterBorder: "transparent",
    caret: "#7C79F0",
    selection: "rgba(91,87,224,0.25)",
  },
});

function getLanguageExtension(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const name = filename.toLowerCase();
  if (name === "dockerfile") return [];
  switch (ext) {
    case "py":
      return [python()];
    case "ts":
      return [javascript({ typescript: true })];
    case "tsx":
      return [javascript({ typescript: true, jsx: true })];
    case "js":
      return [javascript()];
    case "jsx":
      return [javascript({ jsx: true })];
    case "css":
      return [css()];
    case "html":
      return [html()];
    case "json":
      return [json()];
    default:
      return [];
  }
}

// ── Types ──────────────────────────────────────────────────────────────────────

type McpPhase =
  | "idle"
  | "building"
  | "testing"
  | "verified"
  | "failed"
  | "ready"
  | "stopped"
  | "deploying"
  | "deployed";

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
  container_id?: string | null;
  container_port?: number | null;
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
  "deployed",
];

const GENERATING_PHASES: McpPhase[] = ["building"];

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
  deploying: {
    label: "Deploying…",
    pill: "border-indigo-200 bg-indigo-50 text-indigo-700",
    dotCls: "bg-indigo-500",
    spin: true,
  },
  deployed: {
    label: "Deployed",
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
): Promise<{ stored: string[]; hints: Record<string, string | null> }> {
  const r = await apiFetch(`/api/mcp-studio/servers/${id}/secrets`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ secrets }),
  });
  if (!r.ok)
    throw new Error(`${r.status}: ${await r.text().catch(() => r.statusText)}`);
  return r.json() as Promise<{
    stored: string[];
    hints: Record<string, string | null>;
  }>;
}

async function apiGetSecretsInfo(
  id: string,
): Promise<{ keys: { key_name: string; key_hint: string | null }[] }> {
  const r = await apiFetch(`/api/mcp-studio/servers/${id}/secrets/info`);
  if (!r.ok) return { keys: [] };
  return r.json() as Promise<{
    keys: { key_name: string; key_hint: string | null }[];
  }>;
}

async function apiRevealSecrets(
  id: string,
): Promise<{ values: Record<string, string> }> {
  const r = await apiFetch(`/api/mcp-studio/servers/${id}/secrets/reveal`);
  if (!r.ok)
    throw new Error(`${r.status}: ${await r.text().catch(() => r.statusText)}`);
  return r.json() as Promise<{ values: Record<string, string> }>;
}

async function apiDeploy(id: string): Promise<McpBuildStatus> {
  const r = await apiFetch(`/api/mcp-studio/servers/${id}/deploy`, {
    method: "POST",
  });
  if (!r.ok)
    throw new Error(`${r.status}: ${await r.text().catch(() => r.statusText)}`);
  return r.json() as Promise<McpBuildStatus>;
}

async function apiUndeploy(id: string): Promise<McpBuildStatus> {
  const r = await apiFetch(`/api/mcp-studio/servers/${id}/undeploy`, {
    method: "POST",
  });
  if (!r.ok)
    throw new Error(`${r.status}: ${await r.text().catch(() => r.statusText)}`);
  return r.json() as Promise<McpBuildStatus>;
}

async function apiConnect(
  id: string,
): Promise<{ sse_url: string; server_name: string }> {
  const r = await apiFetch(`/api/mcp-studio/servers/${id}/connect`, {
    method: "POST",
  });
  if (!r.ok)
    throw new Error(`${r.status}: ${await r.text().catch(() => r.statusText)}`);
  return r.json() as Promise<{ sse_url: string; server_name: string }>;
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
            <FolderOpenIcon className="size-3.5 shrink-0 text-[#7C79F0]" />
          ) : (
            <FolderIcon className="size-3.5 shrink-0 text-[#7C79F0]" />
          )}
          {open ? (
            <ChevronDownIcon className="size-3 shrink-0 text-stone-400" />
          ) : (
            <ChevronRightIcon className="size-3 shrink-0 text-stone-400" />
          )}
          <span className="truncate text-stone-500">{node.name}</span>
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
          ? "bg-indigo-50 text-stone-900"
          : "text-stone-500 hover:bg-stone-100 hover:text-stone-700",
      )}
      style={{ paddingLeft: `${8 + depth * 12}px` }}
    >
      <FileIcon
        className={cn(
          "size-3.5 shrink-0",
          isSelected ? "text-[#7C79F0]" : "text-stone-400",
        )}
      />
      <span className="truncate">{node.name}</span>
      {isEntrypoint && (
        <span
          className={cn(
            "ml-auto rounded px-1 py-0.5 text-[9px] font-medium",
            isSelected
              ? "bg-indigo-100 text-[#7C79F0]"
              : "bg-stone-100 text-stone-400",
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
        <span className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase">
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

function SyntaxCodeViewer({
  filename,
  code,
}: {
  filename: string;
  code: string;
}) {
  const [copied, setCopied] = useState(false);
  const extensions = useMemo(() => getLanguageExtension(filename), [filename]);

  const handleCopy = () => {
    void navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div
      className="flex min-h-0 flex-1 flex-col overflow-hidden"
      style={{ background: "#13141a" }}
    >
      {/* tab bar */}
      <div className="flex items-center gap-0 border-b border-stone-200 bg-white">
        <div className="flex items-center gap-2 border-r border-stone-200 px-3 py-2">
          <span className="text-xs text-stone-600">{filename}</span>
          <span className="size-1.5 rounded-full bg-[#5B57E0]" />
        </div>
        <button
          onClick={handleCopy}
          className="mr-3 ml-auto flex items-center gap-1 text-xs text-stone-400 transition-colors hover:text-stone-700"
        >
          {copied ? (
            <CheckIcon className="size-3 text-emerald-400" />
          ) : (
            <ClipboardIcon className="size-3" />
          )}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {/* CodeMirror editor */}
      <div className="min-h-0 flex-1 overflow-auto">
        <CodeMirror
          value={code}
          extensions={extensions}
          theme={cmDarkTheme}
          readOnly
          editable={false}
          basicSetup={{
            lineNumbers: true,
            highlightActiveLineGutter: false,
            highlightActiveLine: false,
            foldGutter: false,
            dropCursor: false,
            allowMultipleSelections: false,
            indentOnInput: false,
            syntaxHighlighting: true,
            bracketMatching: false,
            closeBrackets: false,
            autocompletion: false,
            rectangularSelection: false,
            crosshairCursor: false,
            searchKeymap: false,
            completionKeymap: false,
            lintKeymap: false,
          }}
          style={{ fontSize: "12px", height: "100%" }}
          className="h-full"
        />
      </div>
    </div>
  );
}

function CodePlaceholder({ phase }: { phase: McpPhase }) {
  const isGenerating = GENERATING_PHASES.includes(phase);
  return (
    <div
      className={cn(
        "flex flex-1 flex-col items-center justify-center gap-3 bg-white",
        isGenerating ? "text-stone-400" : "text-stone-300",
      )}
    >
      {isGenerating ? (
        <Loader2Icon className="size-8 animate-spin text-stone-400" />
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, isLoading]);

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

  const displayMessages = useMemo(() => {
    return messages.filter((msg) => {
      if ((msg as { name?: string }).name === "summary") return false;
      if (msg.type === "tool") return false;
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

  // Index of the last AI message (for streaming cursor)
  const lastAiMsgIdx = useMemo(() => {
    let idx = -1;
    for (let i = displayMessages.length - 1; i >= 0; i--) {
      if (displayMessages[i]?.type === "ai") {
        idx = i;
        break;
      }
    }
    return idx;
  }, [displayMessages]);

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
    <div className="flex h-full flex-col bg-[#F6F5F1]">
      {/* header strip */}
      <div className="flex items-center justify-between border-b border-[#E4E2DB] px-4 py-2.5">
        <span className="text-[10px] font-semibold tracking-widest text-[#6C6F79] uppercase">
          Build Activity
        </span>
        {isLoading && (
          <span className="flex items-center gap-1.5 text-[11px] font-medium text-[#5B57E0]">
            <span className="size-1.5 animate-pulse rounded-full bg-[#5B57E0]" />
            Agent working
          </span>
        )}
      </div>

      {/* feed */}
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {!hasContent && isLoading && (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <div className="flex size-10 items-center justify-center rounded-full border border-[#E4E2DB] bg-[#FCFBF8]">
              <Loader2Icon className="size-4 animate-spin text-[#5B57E0]" />
            </div>
            <p className="text-sm font-medium text-[#1B1D23]">
              Agent is writing your server…
            </p>
            <p className="text-xs text-[#6C6F79]">
              This usually takes 30–60 seconds
            </p>
          </div>
        )}
        {!hasContent && !isLoading && (
          <div className="flex flex-col items-center gap-2 py-16 text-center">
            <div className="flex size-10 items-center justify-center rounded-full border border-[#E4E2DB] bg-[#FCFBF8]">
              <SparklesIcon className="size-4 text-[#5B57E0]" />
            </div>
            <p className="text-sm font-medium text-[#6C6F79]">
              No activity yet
            </p>
            <p className="text-xs text-[#6C6F79]">
              Ask the agent to fix, extend, or explain its code.
            </p>
          </div>
        )}

        {displayMessages.map((msg, _msgIdx) => {
          const id = (msg as { id?: string }).id ?? `msg-${_msgIdx}`;
          const isLastAi = _msgIdx === lastAiMsgIdx;

          if (msg.type === "human") {
            const text = extractContentText(msg.content);
            if (!text) return null;
            return (
              <div key={id} className="flex justify-end">
                <div className="max-w-[82%] rounded-2xl rounded-br-sm border border-[#E4E2DB] bg-[#EFEEE8] px-3.5 py-2.5 text-sm leading-relaxed text-[#1B1D23] shadow-sm">
                  {text}
                </div>
              </div>
            );
          }

          if (msg.type === "ai") {
            const toolCalls =
              (msg as { tool_calls?: StreamToolCall[] }).tool_calls ?? [];
            const text = extractContentText(msg.content);
            const thinking = extractThinkingText(msg);
            const isStreaming = isLoading && isLastAi;

            return (
              <div key={id} className="space-y-2">
                {/* Thinking disclosure */}
                {thinking && (
                  <details className="group">
                    <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[11px] text-[#6C6F79] select-none hover:text-[#1B1D23]">
                      <ChevronRightIcon className="size-3 transition-transform group-open:rotate-90" />
                      Thinking
                    </summary>
                    <div className="mt-1.5 ml-4 rounded-lg border border-[#E4E2DB] bg-[#EFEEE8] px-3 py-2.5 text-[11px] leading-relaxed whitespace-pre-wrap text-[#6C6F79]">
                      {thinking}
                    </div>
                  </details>
                )}

                {/* AI text bubble */}
                {(text || isStreaming) && (
                  <div className="flex items-start gap-2.5">
                    <div className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-[#5B57E0]">
                      <SparklesIcon className="size-3 text-white" />
                    </div>
                    <div className="max-w-[82%] min-w-0 rounded-2xl rounded-tl-sm border border-[#E4E2DB] bg-[#FCFBF8] px-3.5 py-2.5 shadow-sm">
                      {text ? (
                        <>
                          <MessageResponse
                            remarkPlugins={streamdownPlugins.remarkPlugins}
                            rehypePlugins={streamdownPlugins.rehypePlugins}
                            className="text-sm leading-relaxed text-[#33363E] [&_a]:text-[#5B57E0] [&_a]:underline [&_a]:underline-offset-2 [&_blockquote]:border-l-2 [&_blockquote]:border-[#E4E2DB] [&_blockquote]:pl-3 [&_blockquote]:text-[#6C6F79] [&_code]:rounded [&_code]:border [&_code]:border-[#E4E2DB] [&_code]:bg-white [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-xs [&_code]:text-[#1B1D23] [&_h1]:mb-2 [&_h1]:text-base [&_h1]:font-semibold [&_h1]:text-[#1B1D23] [&_h2]:mb-1.5 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-[#1B1D23] [&_h3]:text-sm [&_h3]:font-medium [&_h3]:text-[#1B1D23] [&_li]:mb-0.5 [&_ol]:mb-2 [&_ol]:list-decimal [&_ol]:pl-4 [&_p]:mb-1.5 [&_p:last-child]:mb-0 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:border [&_pre]:border-[#E4E2DB] [&_pre]:bg-[#131519] [&_pre]:p-3 [&_pre_code]:border-0 [&_pre_code]:bg-transparent [&_pre_code]:text-[#E9EBF0] [&_strong]:font-semibold [&_strong]:text-[#1B1D23] [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:pl-4"
                          >
                            {text}
                          </MessageResponse>
                          {isStreaming && (
                            <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse rounded-sm bg-[#5B57E0] align-middle" />
                          )}
                        </>
                      ) : (
                        <span className="flex items-center gap-1 py-0.5">
                          <span className="size-1.5 animate-bounce rounded-full bg-[#5B57E0] opacity-60 [animation-delay:0ms]" />
                          <span className="size-1.5 animate-bounce rounded-full bg-[#5B57E0] opacity-60 [animation-delay:150ms]" />
                          <span className="size-1.5 animate-bounce rounded-full bg-[#5B57E0] opacity-60 [animation-delay:300ms]" />
                        </span>
                      )}
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
                      className={cn(
                        "flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 transition-colors",
                        isDone
                          ? "border-[#E4E2DB] bg-[#FCFBF8]"
                          : "border-[#E4E2DB] bg-[#EFEEE8]",
                      )}
                    >
                      <div
                        className={cn(
                          "mt-0.5 size-1.5 shrink-0 rounded-full",
                          isDone ? "bg-[#5B57E0]" : "bg-[#C4C3E8]",
                        )}
                      />
                      <div className="min-w-0 flex-1">
                        <span
                          className={cn(
                            "text-xs font-medium",
                            isDone ? "text-[#1B1D23]" : "text-[#6C6F79]",
                          )}
                        >
                          {label}
                        </span>
                        {detail && (
                          <span className="ml-2 truncate font-mono text-[10px] text-[#6C6F79]">
                            {detail}
                          </span>
                        )}
                        {isDone && result && (
                          <p className="mt-0.5 text-[10px] leading-relaxed text-[#6C6F79]">
                            {toolResultSummary(result.name, result.text)}
                          </p>
                        )}
                      </div>
                      {!isDone && (
                        <Loader2Icon className="mt-0.5 size-3 shrink-0 animate-spin text-[#5B57E0]" />
                      )}
                    </div>
                  );
                })}
              </div>
            );
          }

          return null;
        })}

        <div ref={bottomRef} />
      </div>

      {/* input */}
      <div className="border-t border-[#E4E2DB] p-3">
        <div className="flex items-end gap-2 rounded-xl border border-[#E4E2DB] bg-[#FCFBF8] px-3 py-2 shadow-sm transition-all focus-within:border-[#5B57E0] focus-within:shadow-[0_0_0_3px_rgba(91,87,224,0.1)]">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask the agent to fix, extend, or explain…"
            rows={2}
            disabled={isLoading}
            className="flex-1 resize-none bg-transparent text-sm text-[#1B1D23] placeholder:text-[#A8ABB3] focus:outline-none disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="mb-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-[#5B57E0] text-white transition-colors hover:bg-[#4A46D0] disabled:opacity-30"
          >
            {isLoading ? (
              <Loader2Icon className="size-3.5 animate-spin" />
            ) : (
              <SendIcon className="size-3.5" />
            )}
          </button>
        </div>
        <p className="mt-1.5 text-center text-[10px] text-[#A8ABB3]">
          Enter to send · Shift+Enter for newline
        </p>
      </div>
    </div>
  );
}

// ── Generating view ────────────────────────────────────────────────────────────

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

  const stream = useStream<AgentThreadState>({
    client: getAPIClient(),
    assistantId: "lead_agent",
    threadId: threadId ?? "",
    reconnectOnMount: true,
    fetchStateHistory: threadId ? { limit: 1 } : undefined,
  });

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
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* LEFT: activity feed — 50% */}
      <div className="flex w-1/2 shrink-0 flex-col border-r border-[#E4E2DB]">
        {threadId ? (
          <BuildActivityFeed
            messages={stream.messages ?? []}
            isLoading={stream.isLoading}
            onSubmit={handleSubmit}
            onBuildUpdated={onBuildUpdated}
          />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-[#F6F5F1] p-6 text-center">
            <div className="flex size-10 items-center justify-center rounded-full border border-[#E4E2DB] bg-[#FCFBF8]">
              <TerminalIcon className="size-4 text-[#6C6F79]" />
            </div>
            <p className="text-sm font-medium text-[#1B1D23]">
              No chat session linked
            </p>
            <p className="text-xs text-[#6C6F79]">
              Create a new server from the Start tab to get an embedded chat.
            </p>
          </div>
        )}
      </div>

      {/* RIGHT: code panel — 50% */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-white">
        {/* server info card */}
        <div className="border-b border-stone-200 bg-white px-5 py-3">
          <div className="flex items-center gap-3">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-stone-200 bg-stone-50">
              <TerminalIcon className="size-4 text-[#7C79F0]" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h2 className="truncate text-sm font-semibold text-stone-900">
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
                <p className="mt-0.5 line-clamp-1 text-[11px] leading-relaxed text-stone-400">
                  {server.description}
                </p>
              )}
            </div>
          </div>
        </div>

        {/* detected tools */}
        {tools_discovered.length > 0 && (
          <div className="border-b border-stone-200 bg-white px-5 py-2.5">
            <button
              onClick={() => setToolsExpanded((v) => !v)}
              className="flex items-center gap-2 text-[10px] font-semibold tracking-wider text-stone-400 uppercase hover:text-stone-600"
            >
              <ChevronRightIcon
                className={cn(
                  "size-3 transition-transform",
                  toolsExpanded && "rotate-90",
                )}
              />
              Detected tools ({tools_discovered.length})
            </button>
            {toolsExpanded && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {tools_discovered.map((t) => (
                  <span
                    key={t.name}
                    className="flex items-center gap-1 rounded border border-stone-200 bg-stone-50 px-2 py-1 font-mono text-[10px] text-stone-600"
                  >
                    {t.name}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* errors banner */}
        {errors.length > 0 && phase !== "building" && (
          <div className="border-b border-red-900/30 bg-red-950/50 px-5 py-2">
            {errors.map((e, i) => (
              <p
                key={i}
                className="flex items-center gap-1.5 text-xs text-red-400"
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
              <div className="w-44 shrink-0 border-r border-stone-200 bg-white">
                <FileTreePanel
                  files={files}
                  selectedPath={selectedFile}
                  onSelect={setSelectedFile}
                />
              </div>
              <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
                {files[selectedFile] !== undefined ? (
                  <SyntaxCodeViewer
                    filename={selectedFile}
                    code={files[selectedFile]}
                  />
                ) : liveCode ? (
                  <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
                    {stream.isLoading && (
                      <div className="absolute top-2 right-3 z-10 flex items-center gap-1 rounded border border-stone-200 bg-white/90 px-2 py-0.5 text-[10px] text-[#7C79F0]">
                        <Loader2Icon className="size-2.5 animate-spin" />{" "}
                        streaming
                      </div>
                    )}
                    <SyntaxCodeViewer filename="server.py" code={liveCode} />
                  </div>
                ) : (
                  <CodePlaceholder phase={phase} />
                )}
              </div>
            </>
          ) : liveCode ? (
            <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
              {stream.isLoading && (
                <div className="absolute top-2 right-3 z-10 flex items-center gap-1 rounded border border-stone-200 bg-white/90 px-2 py-0.5 text-[10px] text-[#7C79F0]">
                  <Loader2Icon className="size-2.5 animate-spin" /> streaming
                </div>
              )}
              <SyntaxCodeViewer filename="server.py" code={liveCode} />
            </div>
          ) : (
            <CodePlaceholder phase={phase} />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Secrets panel ──────────────────────────────────────────────────────────────

// storedInfo: key_name → hint string (last 5 chars) or null (stored but no hint available)
// undefined = not stored at all
type StoredInfo = Map<string, string | null>;

function SecretRow({
  keyName,
  hint,
  serverId,
  value,
  onChange,
}: {
  keyName: string;
  hint: string | null | undefined; // undefined = not stored
  serverId: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const isStored = hint !== undefined;
  const [showReveal, setShowReveal] = useState(false);
  const [revealed, setRevealed] = useState<string | null>(null);
  const [revealing, setRevealing] = useState(false);

  // When user starts typing a new value, hide any revealed value
  const handleChange = (v: string) => {
    if (v) {
      setRevealed(null);
      setShowReveal(false);
    }
    onChange(v);
  };

  const handleEye = async () => {
    // If user is typing a new value, just toggle visibility of what they're typing
    if (value) {
      setShowReveal((p) => !p);
      return;
    }
    // If a stored value is revealed, hide it
    if (revealed !== null) {
      setRevealed(null);
      setShowReveal(false);
      return;
    }
    // Reveal from server
    if (!isStored) return;
    setRevealing(true);
    try {
      const resp = await apiRevealSecrets(serverId);
      const plaintext = resp.values[keyName];
      if (plaintext !== undefined) {
        setRevealed(plaintext);
        setShowReveal(true);
      }
    } catch {
      // silently ignore; user can try again
    } finally {
      setRevealing(false);
    }
  };

  // Determine what to display in the input
  const displayValue = revealed ?? value;
  const inputType = showReveal ? "text" : "password";

  // Placeholder: show hint if stored, otherwise prompt
  let placeholder = "Enter value…";
  if (isStored) {
    const tail = hint ?? "";
    placeholder = `•••••${tail} — click 🔓 to reveal or type to update`;
  }

  return (
    <div className="rounded-xl border border-stone-200 bg-stone-50 p-3">
      <div className="mb-1.5 flex items-center justify-between">
        <code className="font-mono text-xs font-semibold text-stone-700">
          {keyName}
        </code>
        {isStored ? (
          <span className="flex items-center gap-1 text-[10px] font-medium text-emerald-600">
            <CheckCircle2Icon className="size-3" />
            {hint ? <span className="font-mono">•••{hint}</span> : "Stored"}
          </span>
        ) : (
          <span className="text-[10px] text-stone-400">Not set</span>
        )}
      </div>
      <div className="flex items-center gap-1">
        <input
          type={inputType}
          autoComplete="new-password"
          placeholder={placeholder}
          value={displayValue}
          onChange={(e) => handleChange(e.target.value)}
          className="flex-1 rounded-lg border border-stone-200 bg-white px-2 py-1.5 font-mono text-xs text-stone-900 placeholder:text-stone-300 focus:border-[#5B57E0] focus:shadow-[0_0_0_2px_rgba(91,87,224,0.15)] focus:outline-none"
        />
        <button
          type="button"
          onClick={() => void handleEye()}
          disabled={revealing || (!isStored && !value)}
          className="rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600 disabled:opacity-30"
          title={
            revealing
              ? "Revealing…"
              : showReveal || revealed !== null
                ? "Hide"
                : isStored
                  ? "Reveal stored value"
                  : "Show"
          }
        >
          {revealing ? (
            <Loader2Icon className="size-3.5 animate-spin" />
          ) : showReveal || revealed !== null ? (
            <EyeOffIcon className="size-3.5" />
          ) : (
            <EyeIcon className="size-3.5" />
          )}
        </button>
      </div>
    </div>
  );
}

function SecretsSection({
  serverId,
  secretNames,
  storedInfo,
  onStored,
}: {
  serverId: string;
  secretNames: string[];
  storedInfo: StoredInfo;
  onStored: (hints: Record<string, string | null>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retesting, setRetesting] = useState(false);

  if (secretNames.length === 0) return null;

  const hasUnsaved = Object.values(values).some((v) => v.trim());
  const allStored = secretNames.every((k) => storedInfo.has(k));

  const handleSave = async () => {
    const toSave = Object.fromEntries(
      Object.entries(values).filter(([, v]) => v.trim()),
    );
    if (!Object.keys(toSave).length) return;
    setSaving(true);
    setError(null);
    try {
      const result = await apiWriteSecrets(serverId, toSave);
      onStored(result.hints);
      setValues({});
      // Auto re-test after saving so the user sees real test results
      setRetesting(true);
      try {
        await apiRetest(serverId);
      } catch {
        // re-test failure is non-fatal; user can trigger manually
      } finally {
        setRetesting(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="space-y-3">
        <p className="text-[11px] leading-relaxed text-stone-400">
          Encrypted at rest · auto-detected from code · never sent to AI.
        </p>
        {secretNames.map((key) => (
          <SecretRow
            key={key}
            keyName={key}
            hint={
              storedInfo.has(key) ? (storedInfo.get(key) ?? null) : undefined
            }
            serverId={serverId}
            value={values[key] ?? ""}
            onChange={(v) => setValues((prev) => ({ ...prev, [key]: v }))}
          />
        ))}

        {error && <p className="text-xs text-red-400">{error}</p>}

        <Button
          size="sm"
          className="w-full bg-stone-900 text-white hover:bg-stone-700"
          disabled={saving || retesting || !hasUnsaved}
          onClick={() => void handleSave()}
        >
          {saving ? (
            <>
              <Loader2Icon className="size-3.5 animate-spin" /> Saving…
            </>
          ) : retesting ? (
            <>
              <Loader2Icon className="size-3.5 animate-spin" /> Re-testing…
            </>
          ) : allStored ? (
            "Update secrets & Re-test"
          ) : (
            "Save secrets & Re-test"
          )}
        </Button>
      </div>
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
  testResult?: {
    ok: boolean;
    output_type?: string;
    output?: string;
    error?: string;
  };
  onRetest?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  // Derive badge label + colour from output_type (new) falling back to ok (legacy)
  const badgeInfo = (() => {
    if (!testResult) return null;
    const ot = testResult.output_type;
    if (
      ot === "pass" ||
      (!ot && testResult.ok && !testResult.output && !testResult.error)
    )
      return {
        label: "pass",
        cls: "border-emerald-200 bg-emerald-50 text-emerald-700",
      };
    if (ot === "auth" || (!ot && testResult.ok))
      return {
        label: "401",
        cls: "border-amber-200 bg-amber-50 text-amber-700",
        title:
          "Callable — placeholder credentials returned 401 (expected during sandbox testing)",
      };
    if (ot === "args")
      return {
        label: "args",
        cls: "border-blue-200 bg-blue-50 text-blue-600",
        title:
          "Callable — requires arguments not supplied in automated testing",
      };
    if (ot === "error" || !testResult.ok)
      return { label: "fail", cls: "border-red-200 bg-red-50 text-red-600" };
    return {
      label: "pass",
      cls: "border-emerald-200 bg-emerald-50 text-emerald-700",
    };
  })();

  return (
    <div className="overflow-hidden rounded-xl border border-stone-200 bg-white shadow-sm transition-colors hover:border-stone-300">
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
            <code className="font-mono text-sm font-semibold text-stone-900">
              {tool.name}
            </code>
            <span className="rounded border border-stone-200 bg-stone-50 px-1.5 py-0.5 text-[10px] text-stone-400">
              async
            </span>
            {badgeInfo && (
              <span
                className={cn(
                  "rounded-full border px-1.5 py-0.5 text-[10px] font-medium",
                  badgeInfo.cls,
                )}
                title={badgeInfo.title}
              >
                {badgeInfo.label}
              </span>
            )}
          </div>
          {!expanded && tool.description && (
            <p className="mt-0.5 line-clamp-1 text-xs text-stone-400">
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
            className="rounded-lg p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
            title="Re-test"
          >
            <RefreshCwIcon className="size-3.5" />
          </button>
        )}
      </button>
      {expanded && (
        <div className="space-y-2 border-t border-stone-200 px-4 py-3">
          {tool.description && (
            <p className="text-sm leading-relaxed text-stone-500">
              {tool.description}
            </p>
          )}
          {testResult?.error && (
            <div className="rounded-lg border border-[#E4E2DB] bg-[#FCFBF8] px-3 py-2 font-mono text-xs text-red-600">
              {testResult.error}
            </div>
          )}
          {testResult?.output && (
            <div className="rounded-lg border border-[#E4E2DB] bg-[#FCFBF8] px-3 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap text-[#1B1D23]">
              {testResult.output}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ToolsView({
  server,
  serverId,
  buildStatus,
  storedInfo,
  onStored,
  onRetested,
}: {
  server: McpServerResponse;
  serverId: string;
  buildStatus: McpBuildStatus;
  storedInfo: StoredInfo;
  onStored: (hints: Record<string, string | null>) => void;
  onRetested: (s: McpBuildStatus) => void;
}) {
  const {
    phase,
    errors,
    tools_discovered,
    test_results,
    detected_secret_names,
  } = buildStatus;
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
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* header — MCP name + re-test controls */}
      <div className="flex items-center gap-3 border-b border-stone-200 bg-white px-5 py-3">
        <div className="flex min-w-0 flex-1 items-center gap-2.5">
          <div className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-stone-200 bg-stone-50">
            <BoxIcon className="size-3.5 text-[#7C79F0]" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-stone-900">
              {server.name}
            </p>
            <p className="text-[10px] text-stone-400">
              {tools_discovered.length} tool
              {tools_discovered.length !== 1 ? "s" : ""} discovered
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-lg border border-stone-200 bg-stone-50 px-2.5 py-1 text-xs text-stone-500">
            Sandbox
          </span>
          {errors.length > 0 ? (
            <span className="flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-2.5 py-1 text-xs text-red-600">
              <XCircleIcon className="size-3" /> {errors.length} error
              {errors.length !== 1 ? "s" : ""}
            </span>
          ) : (
            <span className="flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs text-emerald-700">
              <CheckCircle2Icon className="size-3" /> 0 errors
            </span>
          )}
          <button
            onClick={() => void handleRetest()}
            disabled={retesting}
            className="rounded-lg p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
            title="Re-test all"
          >
            <RotateCcwIcon
              className={cn("size-4", retesting && "animate-spin")}
            />
          </button>
        </div>
      </div>

      {/* status banners */}
      {dp === "verified" && (
        <div className="flex items-center gap-2.5 border-b border-emerald-200 bg-emerald-600 px-5 py-2.5">
          <div className="flex size-6 items-center justify-center rounded-full bg-white/20">
            <CheckCircle2Icon className="size-3.5 text-white" />
          </div>
          <span className="text-sm font-medium text-white">
            Sandbox verified — all tools tested successfully
          </span>
        </div>
      )}
      {dp === "needs_secrets" && (
        <div className="flex items-center gap-2.5 border-b border-amber-200 bg-amber-500 px-5 py-2.5">
          <div className="flex size-6 items-center justify-center rounded-full bg-white/20">
            <KeyIcon className="size-3.5 text-white" />
          </div>
          <span className="text-sm font-medium text-white">
            Needs secrets — add API keys below and re-test
          </span>
        </div>
      )}
      {dp === "failed" && (
        <div className="flex items-center gap-3 border-b border-red-900/20 bg-red-700 px-5 py-3">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-white/15">
            <ShieldXIcon className="size-4 text-white" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-white">
              Blocked by Security Scan
            </p>
            <p className="text-[11px] text-red-200">
              {errors.length} {errors.length === 1 ? "issue" : "issues"}{" "}
              prevented execution
            </p>
          </div>
          <span className="flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1 text-[11px] font-semibold text-white ring-1 ring-white/20">
            <XCircleIcon className="size-3" />
            {errors.length} {errors.length === 1 ? "error" : "errors"}
          </span>
        </div>
      )}
      {dp === "testing" && (
        <div className="flex items-center gap-2.5 border-b border-orange-200 bg-orange-500 px-5 py-2.5">
          <div className="flex size-6 items-center justify-center rounded-full bg-white/20">
            <ShieldAlertIcon className="size-3.5 text-white" />
          </div>
          <span className="text-sm font-medium text-white">
            Couldn&apos;t verify — server started but no tools found
          </span>
        </div>
      )}

      {/* tool list / error details */}
      <div className="flex-1 space-y-4 overflow-y-auto bg-stone-50 p-4">
        {/* Secrets panel — always shown when secrets are detected */}
        {detected_secret_names.length > 0 && (
          <div className="overflow-hidden rounded-xl border border-stone-200 bg-white shadow-sm">
            <div className="flex items-center gap-2 border-b border-stone-200 px-4 py-3">
              <KeyIcon className="size-3.5 text-[#7C79F0]" />
              <h3 className="text-xs font-semibold text-stone-700">
                API Secrets
              </h3>
              {detected_secret_names.some((k) => !storedInfo.has(k)) && (
                <span className="ml-auto flex items-center gap-1 rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-[10px] font-medium text-red-600">
                  <span className="size-1.5 rounded-full bg-red-500" />
                  {
                    detected_secret_names.filter((k) => !storedInfo.has(k))
                      .length
                  }{" "}
                  missing
                </span>
              )}
              {detected_secret_names.every((k) => storedInfo.has(k)) && (
                <span className="ml-auto flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                  <CheckCircle2Icon className="size-2.5" /> All set
                </span>
              )}
            </div>
            <div className="p-4">
              <SecretsSection
                serverId={serverId}
                secretNames={detected_secret_names}
                storedInfo={storedInfo}
                onStored={onStored}
              />
            </div>
          </div>
        )}

        {/* tools section label */}
        {tools_discovered.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase">
                Tools
              </span>
              <div className="h-px flex-1 bg-stone-200" />
              <span className="font-mono text-[10px] text-[#5B57E0]">
                {tools_discovered.length}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2">
              <span className="text-[10px] text-stone-500">
                Sandbox uses placeholder credentials —
              </span>
              <span className="flex items-center gap-1 text-[10px]">
                <span className="rounded-full border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
                  pass
                </span>
                <span className="text-stone-400">real response</span>
              </span>
              <span className="flex items-center gap-1 text-[10px]">
                <span className="rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                  401
                </span>
                <span className="text-stone-400">
                  callable, real key used at runtime
                </span>
              </span>
              <span className="flex items-center gap-1 text-[10px]">
                <span className="rounded-full border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-600">
                  args
                </span>
                <span className="text-stone-400">
                  callable, needs arguments
                </span>
              </span>
            </div>
          </div>
        )}

        {dp === "failed" && errors.length > 0 ? (
          <div className="flex flex-col gap-4">
            {/* blocked illustration */}
            <div className="flex flex-col items-center gap-3 pt-6 pb-2 text-center">
              <div className="relative flex size-16 items-center justify-center rounded-2xl border border-red-900/40 bg-red-950/30">
                <ShieldXIcon className="size-8 text-red-400" />
                <span className="absolute -top-1.5 -right-1.5 flex size-5 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white ring-2 ring-stone-50">
                  {errors.length}
                </span>
              </div>
              <div>
                <h3 className="text-base font-semibold text-stone-900">
                  Server blocked by security scan
                </h3>
                <p className="mt-0.5 text-sm text-stone-500">
                  {errors.length === 1 ? "1 issue" : `${errors.length} issues`}{" "}
                  prevented sandbox execution
                </p>
              </div>
            </div>

            {/* error cards */}
            {errors.map((error, i) => {
              const isModelCfgError = error
                .toLowerCase()
                .includes("moderation model");
              return (
                <div
                  key={i}
                  className="overflow-hidden rounded-xl border border-stone-200 bg-white shadow-sm"
                >
                  <div className="flex items-center gap-2.5 border-b border-stone-200 bg-red-50 px-4 py-2.5">
                    <ShieldAlertIcon className="size-3.5 shrink-0 text-red-500" />
                    <span className="text-[11px] font-semibold tracking-wider text-red-600 uppercase">
                      {isModelCfgError
                        ? "Configuration Error"
                        : "Security Block"}
                    </span>
                    <span className="ml-auto rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-medium text-red-600 ring-1 ring-red-200">
                      #{i + 1}
                    </span>
                  </div>
                  <div className="px-4 py-3.5">
                    <p className="text-sm leading-relaxed text-stone-600">
                      {error}
                    </p>
                    {isModelCfgError && (
                      <div className="mt-3.5 rounded-xl border border-amber-900/30 bg-amber-950/20 px-3.5 py-3">
                        <p className="mb-2 text-xs font-semibold text-amber-400">
                          How to fix
                        </p>
                        <ul className="space-y-1.5 text-xs leading-relaxed text-amber-500/80">
                          <li className="flex items-start gap-1.5">
                            <span className="mt-0.5 shrink-0 font-bold">
                              1.
                            </span>
                            <span>
                              Open{" "}
                              <code className="rounded bg-amber-950/40 px-1 py-0.5 font-mono text-[11px] text-amber-400">
                                config.yaml
                              </code>{" "}
                              and set{" "}
                              <code className="rounded bg-amber-950/40 px-1 py-0.5 font-mono text-[11px] text-amber-400">
                                skill_evolution.moderation_model_name
                              </code>{" "}
                              to a valid model name.
                            </span>
                          </li>
                          <li className="flex items-start gap-1.5">
                            <span className="mt-0.5 shrink-0 font-bold">
                              2.
                            </span>
                            <span>
                              Verify the model&apos;s API key is set and the
                              model is accessible.
                            </span>
                          </li>
                          <li className="flex items-start gap-1.5">
                            <span className="mt-0.5 shrink-0 font-bold">
                              3.
                            </span>
                            <span>Re-test once the model is configured.</span>
                          </li>
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {/* re-test CTA */}
            <button
              onClick={() => void handleRetest()}
              disabled={retesting}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-stone-200 bg-white px-4 py-3 text-sm font-medium text-stone-700 shadow-sm transition-all hover:border-stone-300 hover:bg-stone-50 disabled:opacity-50"
            >
              <RotateCcwIcon
                className={cn("size-4", retesting && "animate-spin")}
              />
              {retesting ? "Re-testing…" : "Re-test after fixing"}
            </button>
          </div>
        ) : tools_discovered.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <div className="flex size-12 items-center justify-center rounded-full border border-stone-200 bg-stone-50">
              <BoxIcon className="size-5 text-stone-400" />
            </div>
            <p className="text-sm font-medium text-stone-500">
              No tools discovered yet
            </p>
            {dp !== "verified" && (
              <p className="text-xs text-stone-400">
                Run re-test to discover tools.
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {tools_discovered.map((tool) => (
              <ToolCard
                key={tool.name}
                tool={tool}
                testResult={test_results.find((r) => r.tool === tool.name)}
              />
            ))}
          </div>
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
      <div className="flex flex-1 flex-col items-center justify-center gap-2 bg-white">
        <TerminalIcon className="size-8 text-stone-300" />
        <p className="text-sm text-stone-400">No code available</p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      <div className="w-48 shrink-0 border-r border-stone-200 bg-white">
        <FileTreePanel
          files={files}
          selectedPath={selectedFile}
          onSelect={setSelectedFile}
        />
      </div>
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {files[selectedFile] !== undefined ? (
          <SyntaxCodeViewer
            filename={selectedFile}
            code={files[selectedFile]}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center bg-white">
            <p className="text-sm text-stone-400">Select a file</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Inspect view ──────────────────────────────────────────────────────────────

function InspectView({
  server,
  buildStatus,
  threadId,
  onRetested,
  onAllSecretsStored,
}: {
  server: McpServerResponse;
  buildStatus: McpBuildStatus;
  threadId?: string;
  onRetested: (s: McpBuildStatus) => void;
  onAllSecretsStored?: () => void;
}) {
  const [subTab, setSubTab] = useState<InspectSubTab>("tools");
  const [storedInfo, setStoredInfo] = useState<StoredInfo>(new Map());

  // Load stored key names + hints from DB on mount so state persists across refreshes
  useEffect(() => {
    void apiGetSecretsInfo(server.id).then(({ keys }) => {
      setStoredInfo(new Map(keys.map((k) => [k.key_name, k.key_hint])));
    });
  }, [server.id]);

  const stream = useStream<AgentThreadState>({
    client: getAPIClient(),
    assistantId: "lead_agent",
    threadId: threadId ?? "",
    reconnectOnMount: true,
    fetchStateHistory: threadId ? { limit: 1 } : undefined,
  });

  const handleSubmit = useCallback(
    (text: string) => {
      void stream.submit({
        messages: [{ role: "user", content: text } as unknown as Message],
      });
    },
    [stream],
  );

  const handleStored = (hints: Record<string, string | null>) => {
    setStoredInfo((prev) => {
      const next = new Map(prev);
      for (const [k, h] of Object.entries(hints)) next.set(k, h);
      // Notify the page if all required secrets are now stored
      const required = buildStatus.detected_secret_names;
      if (required.length > 0 && required.every((k) => next.has(k))) {
        onAllSecretsStored?.();
      }
      return next;
    });
  };

  // Auto-refresh: detect completed mcp_build / write_file / str_replace tool calls
  const seenToolCallIds = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!stream.messages?.length) return;
    let needsRefresh = false;
    for (const msg of stream.messages) {
      if (msg.type === "tool") {
        const tm = msg as { tool_call_id?: string; name?: string };
        if (
          tm.tool_call_id &&
          !seenToolCallIds.current.has(tm.tool_call_id) &&
          (tm.name === "mcp_build" ||
            tm.name === "write_file" ||
            tm.name === "str_replace")
        ) {
          seenToolCallIds.current.add(tm.tool_call_id);
          needsRefresh = true;
        }
      }
    }
    if (needsRefresh) {
      void apiGetBuild(server.id).then((build) => {
        if (build) onRetested(build);
      });
    }
  }, [stream.messages, server.id, onRetested]);

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* LEFT: persistent chat feed — 50% */}
      <div className="flex w-1/2 shrink-0 flex-col border-r border-[#E4E2DB]">
        {threadId ? (
          <BuildActivityFeed
            messages={stream.messages ?? []}
            isLoading={stream.isLoading}
            onSubmit={handleSubmit}
          />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-[#F6F5F1] p-6 text-center">
            <div className="flex size-10 items-center justify-center rounded-full border border-[#E4E2DB] bg-[#FCFBF8]">
              <TerminalIcon className="size-4 text-[#6C6F79]" />
            </div>
            <p className="text-sm font-medium text-[#1B1D23]">
              No chat session linked
            </p>
            <p className="text-xs text-[#6C6F79]">
              Create a new server from the Start tab to get an embedded chat.
            </p>
          </div>
        )}
      </div>

      {/* RIGHT: white panel with tabs */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-white">
        <div className="flex items-center gap-0 border-b border-stone-200 bg-white px-5 pt-3">
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
                "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors",
                subTab === id
                  ? "border-b-2 border-[#7C79F0] text-stone-900"
                  : "text-stone-400 hover:text-stone-700",
              )}
            >
              <Icon className="size-3.5" />
              {label}
            </button>
          ))}
        </div>

        <div className="flex min-h-0 flex-1 overflow-hidden">
          {subTab === "tools" && (
            <ToolsView
              server={server}
              serverId={server.id}
              buildStatus={buildStatus}
              storedInfo={storedInfo}
              onStored={handleStored}
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
            className="w-full rounded-xl border border-stone-200 bg-white px-3 py-2.5 text-sm text-stone-900 shadow-sm placeholder:text-stone-400 focus:border-stone-400 focus:ring-2 focus:ring-stone-900/5 focus:outline-none"
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
            className="w-full resize-none rounded-xl border border-stone-200 bg-white px-3 py-2.5 text-sm text-stone-900 shadow-sm placeholder:text-stone-400 focus:border-stone-400 focus:ring-2 focus:ring-stone-900/5 focus:outline-none"
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
                  "rounded-full border px-3 py-1.5 text-xs font-medium transition-all",
                  template === t.id
                    ? "border-stone-900 bg-stone-900 text-white shadow-sm"
                    : "border-stone-200 bg-white text-stone-600 hover:border-stone-300 hover:shadow-sm",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <p className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
            {error}
          </p>
        )}

        <Button
          onClick={() => void doCreate()}
          disabled={!name.trim() || creating}
          className="w-full bg-stone-900 text-white shadow-sm hover:bg-stone-700"
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

// ── Deploy tab ─────────────────────────────────────────────────────────────────

function DeployView({
  server,
  buildStatus,
  allSecretsStored,
  onBuildStatusChanged,
}: {
  server: McpServerResponse;
  buildStatus: McpBuildStatus | null;
  allSecretsStored: boolean;
  onBuildStatusChanged: (s: McpBuildStatus) => void;
}) {
  const [deploying, setDeploying] = useState(false);
  const [undeploying, setUndeploying] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const phase = buildStatus?.phase ?? server.phase ?? "idle";
  const isVerified = phase === "verified";
  const isDeployed = phase === "deployed";
  const isDeploying = phase === "deploying";
  const toolCount = buildStatus?.tools_discovered.length ?? 0;
  const secretCount = buildStatus?.detected_secret_names.length ?? 0;
  const containerPort = buildStatus?.container_port;
  const sseUrl = containerPort ? `http://localhost:${containerPort}/sse` : null;

  const canDeploy =
    allSecretsStored && (isVerified || isDeployed) && !isDeploying;

  const handleDeploy = async () => {
    setDeploying(true);
    setError(null);
    try {
      const result = await apiDeploy(server.id);
      onBuildStatusChanged(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deploy failed");
    } finally {
      setDeploying(false);
    }
  };

  const handleUndeploy = async () => {
    setUndeploying(true);
    setError(null);
    try {
      const result = await apiUndeploy(server.id);
      onBuildStatusChanged(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Undeploy failed");
    } finally {
      setUndeploying(false);
    }
  };

  const copyUrl = () => {
    if (!sseUrl) return;
    void navigator.clipboard.writeText(sseUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 bg-stone-50 p-8">
      {/* Server card */}
      <div className="w-full max-w-sm overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm">
        <div className="flex items-center gap-3 border-b border-stone-200 px-5 py-4">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-stone-200 bg-stone-50">
            <BoxIcon className="size-4 text-[#7C79F0]" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-stone-900">
              {server.name}
            </p>
            <p className="text-[10px] text-stone-400">MCP Server</p>
          </div>
          {isDeployed && (
            <span className="flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[10px] font-medium text-emerald-700">
              <CheckCircle2Icon className="size-3" /> Live
            </span>
          )}
          {isDeploying && (
            <span className="flex items-center gap-1 rounded-full border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-[10px] font-medium text-indigo-700">
              <Loader2Icon className="size-3 animate-spin" /> Deploying
            </span>
          )}
        </div>

        {/* Checklist */}
        <div className="divide-y divide-stone-100 px-5">
          <div className="flex items-center gap-3 py-3">
            {isVerified || isDeployed ? (
              <CheckCircle2Icon className="size-4 shrink-0 text-emerald-500" />
            ) : (
              <div className="size-4 shrink-0 rounded-full border-2 border-stone-200" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-stone-700">
                Sandbox verified
              </p>
              <p className="text-[10px] text-stone-400">
                {toolCount} tool{toolCount !== 1 ? "s" : ""} discovered &amp;
                tested
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 py-3">
            {allSecretsStored ? (
              <CheckCircle2Icon className="size-4 shrink-0 text-emerald-500" />
            ) : (
              <div className="size-4 shrink-0 rounded-full border-2 border-amber-300" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-stone-700">
                API secrets stored
              </p>
              <p className="text-[10px] text-stone-400">
                {secretCount === 0
                  ? "No secrets required"
                  : allSecretsStored
                    ? `${secretCount} key${secretCount !== 1 ? "s" : ""} encrypted in vault`
                    : "Add missing keys on the Build tab"}
              </p>
            </div>
          </div>

          {isDeployed && containerPort && (
            <div className="flex items-center gap-3 py-3">
              <CheckCircle2Icon className="size-4 shrink-0 text-emerald-500" />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-stone-700">
                  Running on port {containerPort}
                </p>
                <p className="text-[10px] text-stone-400">
                  Docker container · SSE transport
                </p>
              </div>
            </div>
          )}
        </div>

        {/* SSE URL */}
        {isDeployed && sseUrl && (
          <div className="border-t border-stone-100 px-5 py-3">
            <p className="mb-1.5 text-[10px] font-semibold tracking-wider text-stone-400 uppercase">
              SSE endpoint
            </p>
            <div className="flex items-center gap-2 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2">
              <code className="min-w-0 flex-1 truncate font-mono text-[11px] text-stone-700">
                {sseUrl}
              </code>
              <button
                onClick={copyUrl}
                className="shrink-0 text-stone-400 hover:text-stone-600"
                title="Copy URL"
              >
                {copied ? (
                  <CheckIcon className="size-3.5 text-emerald-500" />
                ) : (
                  <CopyIcon className="size-3.5" />
                )}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex w-full max-w-sm flex-col gap-2">
        {!isDeployed ? (
          <Button
            className={cn(
              "w-full py-3 text-sm font-semibold transition-all",
              canDeploy
                ? "bg-stone-900 text-white hover:bg-stone-700"
                : "cursor-not-allowed bg-stone-100 text-stone-300",
            )}
            disabled={deploying || !canDeploy}
            onClick={() => void handleDeploy()}
          >
            {deploying ? (
              <>
                <Loader2Icon className="size-4 animate-spin" /> Building &amp;
                starting container…
              </>
            ) : (
              "Deploy to Docker"
            )}
          </Button>
        ) : (
          <div className="flex flex-col gap-2">
            <Button
              className="w-full border border-stone-200 bg-white py-3 text-sm font-semibold text-stone-700 shadow-sm hover:bg-stone-50"
              disabled={deploying}
              onClick={() => void handleDeploy()}
            >
              {deploying ? (
                <>
                  <Loader2Icon className="size-4 animate-spin" /> Re-deploying…
                </>
              ) : (
                "Re-deploy"
              )}
            </Button>
            <Button
              className="w-full border border-red-200 bg-red-50 py-3 text-sm font-semibold text-red-600 hover:bg-red-100"
              disabled={undeploying}
              onClick={() => void handleUndeploy()}
            >
              {undeploying ? (
                <>
                  <Loader2Icon className="size-4 animate-spin" /> Stopping
                  container…
                </>
              ) : (
                <>
                  <SquareIcon className="size-4" /> Undeploy
                </>
              )}
            </Button>
          </div>
        )}

        {!allSecretsStored && !isDeployed && (
          <p className="text-center text-[11px] text-stone-400">
            Add your API secrets on the Build tab to enable deploy
          </p>
        )}
        {allSecretsStored && !isVerified && !isDeployed && (
          <p className="text-center text-[11px] text-stone-400">
            Run the sandbox test on the Build tab to reach verified phase
          </p>
        )}
        {isDeployed && (
          <p className="text-center text-[11px] text-stone-400">
            Go to the Connect tab to wire this server into the agent
          </p>
        )}
        {error && <p className="text-center text-xs text-red-500">{error}</p>}
      </div>

      {/* Docker note */}
      <p className="max-w-sm text-center text-[10px] leading-relaxed text-stone-400">
        Requires Docker installed and running on this host. Secrets are injected
        as container env vars and are never written to disk or logs.
      </p>
    </div>
  );
}

// ── Connect tab ────────────────────────────────────────────────────────────────

function ConnectView({
  server,
  buildStatus,
  onConnected,
}: {
  server: McpServerResponse;
  buildStatus: McpBuildStatus | null;
  onConnected: () => void;
}) {
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [connectedName, setConnectedName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const phase = buildStatus?.phase ?? server.phase ?? "idle";
  const isDeployed = phase === "deployed";
  const containerPort = buildStatus?.container_port;
  const sseUrl = containerPort ? `http://localhost:${containerPort}/sse` : null;

  const handleConnect = async () => {
    setConnecting(true);
    setError(null);
    try {
      const result = await apiConnect(server.id);
      setConnected(true);
      setConnectedName(result.server_name);
      onConnected();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connect failed");
    } finally {
      setConnecting(false);
    }
  };

  const copyUrl = () => {
    if (!sseUrl) return;
    void navigator.clipboard.writeText(sseUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  if (!isDeployed) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 bg-stone-50 p-8">
        <div className="flex size-14 items-center justify-center rounded-2xl border border-stone-200 bg-white shadow-sm">
          <PlugIcon className="size-6 text-stone-300" />
        </div>
        <div className="space-y-1 text-center">
          <p className="text-sm font-medium text-stone-700">
            Deploy first to connect
          </p>
          <p className="text-xs text-stone-400">
            The server needs to be running in Docker before it can be wired into
            the agent.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 bg-stone-50 p-8">
      <div className="w-full max-w-sm overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-stone-200 px-5 py-4">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-stone-200 bg-stone-50">
            <PlugZapIcon className="size-4 text-[#7C79F0]" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-stone-900">
              {server.name}
            </p>
            <p className="text-[10px] text-stone-400">
              Running · port {containerPort}
            </p>
          </div>
          {connected && (
            <span className="flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[10px] font-medium text-emerald-700">
              <CheckCircle2Icon className="size-3" /> Wired in
            </span>
          )}
        </div>

        {/* SSE URL row */}
        {sseUrl && (
          <div className="px-5 py-3">
            <p className="mb-1.5 text-[10px] font-semibold tracking-wider text-stone-400 uppercase">
              SSE endpoint
            </p>
            <div className="flex items-center gap-2 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2">
              <code className="min-w-0 flex-1 truncate font-mono text-[11px] text-stone-700">
                {sseUrl}
              </code>
              <button
                onClick={copyUrl}
                className="shrink-0 text-stone-400 hover:text-stone-600"
                title="Copy"
              >
                {copied ? (
                  <CheckIcon className="size-3.5 text-emerald-500" />
                ) : (
                  <CopyIcon className="size-3.5" />
                )}
              </button>
            </div>
          </div>
        )}

        {/* After connect: show what was registered */}
        {connected && connectedName && (
          <div className="border-t border-stone-100 px-5 py-3">
            <p className="text-[10px] leading-relaxed text-stone-500">
              Added{" "}
              <code className="rounded bg-stone-100 px-1 py-0.5 font-mono text-[10px] text-stone-700">
                {connectedName}
              </code>{" "}
              to{" "}
              <code className="rounded bg-stone-100 px-1 py-0.5 font-mono text-[10px] text-stone-700">
                extensions_config.json
              </code>
              . The agent hot-reloads this file automatically — the new tools
              are available immediately.
            </p>
          </div>
        )}
      </div>

      {/* Connect button */}
      <div className="flex w-full max-w-sm flex-col gap-2">
        <Button
          className={cn(
            "w-full py-3 text-sm font-semibold transition-all",
            connected
              ? "border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
              : "bg-stone-900 text-white hover:bg-stone-700",
          )}
          disabled={connecting}
          onClick={() => void handleConnect()}
        >
          {connecting ? (
            <>
              <Loader2Icon className="size-4 animate-spin" /> Connecting…
            </>
          ) : connected ? (
            <>
              <CheckCircle2Icon className="size-4" /> Re-connect
            </>
          ) : (
            <>
              <PlugZapIcon className="size-4" /> Connect to Agent
            </>
          )}
        </Button>

        {error && <p className="text-center text-xs text-red-500">{error}</p>}
      </div>

      <p className="max-w-sm text-center text-[10px] leading-relaxed text-stone-400">
        Writes the SSE URL into{" "}
        <code className="font-mono">extensions_config.json</code>. The agent
        picks it up via mtime hot-reload — no restart needed.
      </p>
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
  // True when every detected_secret_name has a value stored in the vault.
  // Drives the Deploy tab enabled state and the Deploy button.
  const [allSecretsStored, setAllSecretsStored] = useState(false);
  const pollCountRef = useRef(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Thread persistence: URL param wins; fall back to localStorage
  const [threadId, setThreadId] = useState<string | undefined>(() => {
    if (propThreadId) return propThreadId;
    if (typeof window !== "undefined" && !isNew) {
      return localStorage.getItem(`mcp_thread_${serverId}`) ?? undefined;
    }
    return undefined;
  });

  useEffect(() => {
    if (isNew) return;
    if (propThreadId) {
      setThreadId(propThreadId);
      try {
        localStorage.setItem(`mcp_thread_${serverId}`, propThreadId);
      } catch {
        /* ignore */
      }
    } else if (!threadId) {
      try {
        const stored = localStorage.getItem(`mcp_thread_${serverId}`);
        if (stored) setThreadId(stored);
      } catch {
        /* ignore */
      }
    }
  }, [propThreadId, serverId, isNew, threadId]);

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

  // Recompute allSecretsStored whenever buildStatus changes (detected secrets may update).
  useEffect(() => {
    if (isNew) return;
    const required = buildStatus?.detected_secret_names ?? [];
    if (required.length === 0) {
      setAllSecretsStored(true);
      return;
    }
    void apiGetSecretsInfo(serverId).then(({ keys }) => {
      const stored = new Set(keys.map((k) => k.key_name));
      setAllSecretsStored(required.every((k) => stored.has(k)));
    });
  }, [serverId, isNew, buildStatus]);

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

  const handleBuildStatusChanged = useCallback(
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
    { id: "deploy", label: "Deploy", disabled: isNew || !allSecretsStored },
    {
      id: "connect",
      label: "Connect",
      disabled: isNew || phase !== "deployed",
    },
  ];

  if (!isNew && loading) {
    return (
      <div className="flex size-full items-center justify-center">
        <Loader2Icon className="size-5 animate-spin text-stone-400" />
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
    <div className="flex size-full flex-col overflow-hidden bg-white">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-stone-200 bg-white px-5 py-3.5">
        <Link
          href="/workspace/mcp"
          className="rounded-lg p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
        >
          <ArrowLeftIcon className="size-4" />
        </Link>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase">
            MCP Studio
          </p>
          <h1 className="truncate text-base font-semibold text-stone-900">
            {isNew ? "New MCP Server" : (server?.name ?? "Loading…")}
          </h1>
        </div>
        {!isNew && <PhasePill phase={phase} errors={errors} />}
      </div>

      {/* Lifecycle tab bar */}
      <div className="flex items-center gap-0 border-b border-stone-200 bg-white px-5 pt-3">
        {LIFECYCLE_TABS.map(({ id, label, disabled }) => (
          <button
            key={id}
            onClick={() => !disabled && setActiveTab(id)}
            disabled={disabled}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors",
              disabled
                ? "cursor-not-allowed text-stone-300"
                : activeTab === id
                  ? "border-b-2 border-stone-900 text-stone-900"
                  : "text-stone-400 hover:text-stone-700",
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
              <Button
                size="sm"
                className="bg-stone-900 text-white hover:bg-stone-700"
                onClick={() => setActiveTab("build")}
              >
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
              threadId={threadId}
              onBuildUpdated={refreshBuild}
            />
          ) : (
            <InspectView
              server={server}
              buildStatus={buildStatus}
              threadId={threadId}
              onRetested={handleRetested}
              onAllSecretsStored={() => setAllSecretsStored(true)}
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
        {activeTab === "deploy" && !isNew && server && (
          <DeployView
            server={server}
            buildStatus={buildStatus}
            allSecretsStored={allSecretsStored}
            onBuildStatusChanged={handleBuildStatusChanged}
          />
        )}
        {activeTab === "connect" && !isNew && server && (
          <ConnectView
            server={server}
            buildStatus={buildStatus}
            onConnected={() => {
              void apiGetServer(serverId).then((srv) => {
                if (srv) setServer(srv);
              });
            }}
          />
        )}
      </div>
    </div>
  );
}
