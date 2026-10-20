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
import { revealSecret } from "@/core/mcp-studio/reveal";
import { streamdownPlugins } from "@/core/streamdown";
import type { AgentThreadState } from "@/core/threads/types";
import { cn } from "@/lib/utils";

import { RevealSecretDialog } from "./reveal-secret-dialog";

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
  deploy_steps?: Array<{
    key: string;
    label: string;
    status: "pending" | "running" | "done" | "failed";
    detail: string | null;
  }>;
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
    pill: "border-border bg-muted text-muted-foreground",
    dotCls: "bg-muted-foreground/50",
  },
  building: {
    label: "Generating…",
    pill: "border-warning/30 bg-warning/10 text-warning",
    dotCls: "bg-warning",
    spin: true,
  },
  testing: {
    label: "Couldn't verify",
    pill: "border-warning/30 bg-warning/10 text-warning",
    dotCls: "bg-warning",
  },
  verified: {
    label: "Verified in sandbox",
    pill: "border-success/30 bg-success/10 text-success",
    dotCls: "bg-success",
  },
  ready: {
    label: "Running",
    pill: "border-success/30 bg-success/10 text-success",
    dotCls: "bg-success",
  },
  deploying: {
    label: "Deploying…",
    pill: "border-highlight/30 bg-highlight/10 text-highlight",
    dotCls: "bg-highlight",
    spin: true,
  },
  deployed: {
    label: "Deployed",
    pill: "border-success/30 bg-success/10 text-success",
    dotCls: "bg-success",
  },
  failed: {
    label: "Blocked by scan",
    pill: "border-destructive/30 bg-destructive/10 text-destructive",
    dotCls: "bg-destructive",
  },
  stopped: {
    label: "Stopped",
    pill: "border-border bg-muted text-muted-foreground",
    dotCls: "bg-muted-foreground/50",
  },
  needs_secrets: {
    label: "Needs secrets",
    pill: "border-warning/30 bg-warning/10 text-warning",
    dotCls: "bg-warning",
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
          className="hover:bg-muted flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-sm"
          style={{ paddingLeft: `${8 + depth * 12}px` }}
        >
          {open ? (
            <FolderOpenIcon className="text-highlight size-3.5 shrink-0" />
          ) : (
            <FolderIcon className="text-highlight size-3.5 shrink-0" />
          )}
          {open ? (
            <ChevronDownIcon className="text-muted-foreground size-3 shrink-0" />
          ) : (
            <ChevronRightIcon className="text-muted-foreground size-3 shrink-0" />
          )}
          <span className="text-muted-foreground truncate">{node.name}</span>
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
          ? "text-foreground bg-highlight/10"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
      style={{ paddingLeft: `${8 + depth * 12}px` }}
    >
      <FileIcon
        className={cn(
          "size-3.5 shrink-0",
          isSelected ? "text-highlight" : "text-muted-foreground",
        )}
      />
      <span className="truncate">{node.name}</span>
      {isEntrypoint && (
        <span
          className={cn(
            "ml-auto rounded px-1 py-0.5 text-[9px] font-medium",
            isSelected
              ? "bg-highlight/15 text-highlight"
              : "bg-muted text-muted-foreground",
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
      <div className="border-border flex items-center justify-between border-b px-3 py-2">
        <span className="text-muted-foreground text-[10px] font-semibold tracking-widest uppercase">
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
      <div className="border-border bg-card flex items-center gap-0 border-b">
        <div className="border-border flex items-center gap-2 border-r px-3 py-2">
          <span className="text-muted-foreground text-xs">{filename}</span>
          <span className="bg-highlight size-1.5 rounded-full" />
        </div>
        <button
          onClick={handleCopy}
          className="text-muted-foreground hover:text-foreground mr-3 ml-auto flex items-center gap-1 text-xs transition-colors"
        >
          {copied ? (
            <CheckIcon className="text-success size-3" />
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
        "bg-card flex flex-1 flex-col items-center justify-center gap-3",
        isGenerating ? "text-muted-foreground" : "text-muted-foreground",
      )}
    >
      {isGenerating ? (
        <Loader2Icon className="text-muted-foreground size-8 animate-spin" />
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
    <div className="bg-muted flex h-full flex-col">
      {/* header strip */}
      <div className="border-border flex items-center justify-between border-b px-4 py-2.5">
        <span className="text-muted-foreground text-[10px] font-semibold tracking-widest uppercase">
          Build Activity
        </span>
        {isLoading && (
          <span className="text-highlight flex items-center gap-1.5 text-[11px] font-medium">
            <span className="bg-highlight size-1.5 animate-pulse rounded-full" />
            Agent working
          </span>
        )}
      </div>

      {/* feed */}
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {!hasContent && isLoading && (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <div className="border-border bg-card flex size-10 items-center justify-center rounded-full border">
              <Loader2Icon className="text-highlight size-4 animate-spin" />
            </div>
            <p className="text-foreground text-sm font-medium">
              Agent is writing your server…
            </p>
            <p className="text-muted-foreground text-xs">
              This usually takes 30–60 seconds
            </p>
          </div>
        )}
        {!hasContent && !isLoading && (
          <div className="flex flex-col items-center gap-2 py-16 text-center">
            <div className="border-border bg-card flex size-10 items-center justify-center rounded-full border">
              <SparklesIcon className="text-highlight size-4" />
            </div>
            <p className="text-muted-foreground text-sm font-medium">
              No activity yet
            </p>
            <p className="text-muted-foreground text-xs">
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
                <div className="border-border bg-muted text-foreground max-w-[82%] rounded-2xl rounded-br-sm border px-3.5 py-2.5 text-sm leading-relaxed shadow-sm">
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
                    <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer list-none items-center gap-1.5 text-[11px] select-none">
                      <ChevronRightIcon className="size-3 transition-transform group-open:rotate-90" />
                      Thinking
                    </summary>
                    <div className="border-border bg-muted text-muted-foreground mt-1.5 ml-4 rounded-lg border px-3 py-2.5 text-[11px] leading-relaxed whitespace-pre-wrap">
                      {thinking}
                    </div>
                  </details>
                )}

                {/* AI text bubble */}
                {(text || isStreaming) && (
                  <div className="flex items-start gap-2.5">
                    <div className="bg-highlight mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full">
                      <SparklesIcon className="text-highlight-foreground size-3" />
                    </div>
                    <div className="border-border bg-card max-w-[82%] min-w-0 rounded-2xl rounded-tl-sm border px-3.5 py-2.5 shadow-sm">
                      {text ? (
                        <>
                          <MessageResponse
                            remarkPlugins={streamdownPlugins.remarkPlugins}
                            rehypePlugins={streamdownPlugins.rehypePlugins}
                            className="[&_code]:bg-card text-foreground [&_a]:text-highlight [&_blockquote]:border-border [&_blockquote]:text-muted-foreground [&_code]:border-border [&_code]:text-foreground [&_h1]:text-foreground [&_h2]:text-foreground [&_h3]:text-foreground [&_pre]:border-border [&_strong]:text-foreground text-sm leading-relaxed [&_a]:underline [&_a]:underline-offset-2 [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_code]:rounded [&_code]:border [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-xs [&_h1]:mb-2 [&_h1]:text-base [&_h1]:font-semibold [&_h2]:mb-1.5 [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:text-sm [&_h3]:font-medium [&_li]:mb-0.5 [&_ol]:mb-2 [&_ol]:list-decimal [&_ol]:pl-4 [&_p]:mb-1.5 [&_p:last-child]:mb-0 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:border [&_pre]:bg-[#131519] [&_pre]:p-3 [&_pre_code]:border-0 [&_pre_code]:bg-transparent [&_pre_code]:text-[#E9EBF0] [&_strong]:font-semibold [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:pl-4"
                          >
                            {text}
                          </MessageResponse>
                          {isStreaming && (
                            <span className="bg-highlight ml-0.5 inline-block h-3.5 w-0.5 animate-pulse rounded-sm align-middle" />
                          )}
                        </>
                      ) : (
                        <span className="flex items-center gap-1 py-0.5">
                          <span className="bg-highlight size-1.5 animate-bounce rounded-full opacity-60 [animation-delay:0ms]" />
                          <span className="bg-highlight size-1.5 animate-bounce rounded-full opacity-60 [animation-delay:150ms]" />
                          <span className="bg-highlight size-1.5 animate-bounce rounded-full opacity-60 [animation-delay:300ms]" />
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
                          ? "border-border bg-card"
                          : "border-border bg-muted",
                      )}
                    >
                      <div
                        className={cn(
                          "mt-0.5 size-1.5 shrink-0 rounded-full",
                          isDone ? "bg-highlight" : "bg-highlight/30",
                        )}
                      />
                      <div className="min-w-0 flex-1">
                        <span
                          className={cn(
                            "text-xs font-medium",
                            isDone
                              ? "text-foreground"
                              : "text-muted-foreground",
                          )}
                        >
                          {label}
                        </span>
                        {detail && (
                          <span className="text-muted-foreground ml-2 truncate font-mono text-[10px]">
                            {detail}
                          </span>
                        )}
                        {isDone && result && (
                          <p className="text-muted-foreground mt-0.5 text-[10px] leading-relaxed">
                            {toolResultSummary(result.name, result.text)}
                          </p>
                        )}
                      </div>
                      {!isDone && (
                        <Loader2Icon className="text-highlight mt-0.5 size-3 shrink-0 animate-spin" />
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
      <div className="border-border border-t p-3">
        <div className="border-border bg-card focus-within:border-highlight flex items-end gap-2 rounded-xl border px-3 py-2 shadow-sm transition-all focus-within:shadow-[0_0_0_3px_rgba(91,87,224,0.1)]">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask the agent to fix, extend, or explain…"
            rows={2}
            disabled={isLoading}
            className="text-foreground placeholder:text-muted-foreground flex-1 resize-none bg-transparent text-sm focus:outline-none disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="bg-highlight text-highlight-foreground hover:bg-highlight/90 mb-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg transition-colors disabled:opacity-30"
          >
            {isLoading ? (
              <Loader2Icon className="size-3.5 animate-spin" />
            ) : (
              <SendIcon className="size-3.5" />
            )}
          </button>
        </div>
        <p className="text-muted-foreground mt-1.5 text-center text-[10px]">
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
      <div className="border-border flex w-1/2 shrink-0 flex-col border-r">
        {threadId ? (
          <BuildActivityFeed
            messages={stream.messages ?? []}
            isLoading={stream.isLoading}
            onSubmit={handleSubmit}
            onBuildUpdated={onBuildUpdated}
          />
        ) : (
          <div className="bg-muted flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
            <div className="border-border bg-card flex size-10 items-center justify-center rounded-full border">
              <TerminalIcon className="text-muted-foreground size-4" />
            </div>
            <p className="text-foreground text-sm font-medium">
              No chat session linked
            </p>
            <p className="text-muted-foreground text-xs">
              Create a new server from the Start tab to get an embedded chat.
            </p>
          </div>
        )}
      </div>

      {/* RIGHT: code panel — 50% */}
      <div className="bg-card flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* server info card */}
        <div className="border-border bg-card border-b px-5 py-3">
          <div className="flex items-center gap-3">
            <div className="border-border bg-muted flex size-8 shrink-0 items-center justify-center rounded-lg border">
              <TerminalIcon className="text-highlight size-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h2 className="text-foreground truncate text-sm font-semibold">
                  {server.name}
                </h2>
                {server.language && (
                  <span className="border-border bg-muted text-muted-foreground rounded border px-1.5 py-0.5 text-[10px]">
                    {server.language}
                  </span>
                )}
                {files && (
                  <span className="border-border bg-muted text-muted-foreground rounded border px-1.5 py-0.5 text-[10px]">
                    {Object.keys(files).length}{" "}
                    {Object.keys(files).length === 1 ? "file" : "files"}
                  </span>
                )}
              </div>
              {server.description && (
                <p className="text-muted-foreground mt-0.5 line-clamp-1 text-[11px] leading-relaxed">
                  {server.description}
                </p>
              )}
            </div>
          </div>
        </div>

        {/* detected tools */}
        {tools_discovered.length > 0 && (
          <div className="border-border bg-card border-b px-5 py-2.5">
            <button
              onClick={() => setToolsExpanded((v) => !v)}
              className="text-muted-foreground hover:text-foreground flex items-center gap-2 text-[10px] font-semibold tracking-wider uppercase"
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
                    className="border-border bg-muted text-muted-foreground flex items-center gap-1 rounded border px-2 py-1 font-mono text-[10px]"
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
          <div className="border-destructive/30 bg-destructive/10 border-b px-5 py-2">
            {errors.map((e, i) => (
              <p
                key={i}
                className="text-destructive flex items-center gap-1.5 text-xs"
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
              <div className="border-border bg-card w-44 shrink-0 border-r">
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
                      <div className="border-border bg-card/90 text-highlight absolute top-2 right-3 z-10 flex items-center gap-1 rounded border px-2 py-0.5 text-[10px]">
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
                <div className="border-border bg-card/90 text-highlight absolute top-2 right-3 z-10 flex items-center gap-1 rounded border px-2 py-0.5 text-[10px]">
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
  const [asking, setAsking] = useState(false);
  const eyeRef = useRef<HTMLButtonElement>(null);

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
    // Reveal from server, after the password is re-entered
    if (!isStored) return;
    setAsking(true);
  };

  const reveal = async (password: string): Promise<string | null> => {
    try {
      const result = await revealSecret(serverId, keyName, password);
      if (!result.ok) return result.message;
      setRevealed(result.value);
      setShowReveal(true);
      return null;
    } catch {
      return "Could not reach the server. Try again.";
    }
  };

  // Determine what to display in the input
  const displayValue = revealed ?? value;
  const eyeLabel =
    showReveal || revealed !== null
      ? "Hide"
      : isStored && !value
        ? "Reveal stored value"
        : "Show";
  const inputType = showReveal ? "text" : "password";

  // Placeholder: show hint if stored, otherwise prompt
  let placeholder = "Enter value…";
  if (isStored) {
    const tail = hint ?? "";
    placeholder = `•••••${tail} — reveal with the eye, or type to update`;
  }

  return (
    <div className="border-border bg-muted rounded-xl border p-3">
      <div className="mb-1.5 flex items-center justify-between">
        <code className="text-foreground font-mono text-xs font-semibold">
          {keyName}
        </code>
        {isStored ? (
          <span className="text-success flex items-center gap-1 text-[10px] font-medium">
            <CheckCircle2Icon className="size-3" />
            {hint ? <span className="font-mono">•••{hint}</span> : "Stored"}
          </span>
        ) : (
          <span className="text-muted-foreground text-[10px]">Not set</span>
        )}
      </div>
      <div className="flex items-center gap-1">
        <input
          type={inputType}
          autoComplete="new-password"
          placeholder={placeholder}
          value={displayValue}
          onChange={(e) => handleChange(e.target.value)}
          className="border-border bg-card text-foreground placeholder:text-muted-foreground focus:border-highlight flex-1 rounded-lg border px-2 py-1.5 font-mono text-xs focus:shadow-[0_0_0_2px_rgba(91,87,224,0.15)] focus:outline-none"
        />
        <button
          ref={eyeRef}
          type="button"
          onClick={() => void handleEye()}
          disabled={!isStored && !value}
          className="text-muted-foreground hover:bg-muted hover:text-foreground rounded p-1 disabled:opacity-30"
          title={eyeLabel}
          aria-label={`${eyeLabel}: ${keyName}`}
        >
          {showReveal || revealed !== null ? (
            <EyeOffIcon className="size-3.5" />
          ) : (
            <EyeIcon className="size-3.5" />
          )}
        </button>
      </div>
      <RevealSecretDialog
        open={asking}
        keyName={keyName}
        onOpenChange={setAsking}
        onReveal={reveal}
        returnFocusTo={eyeRef}
      />
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
        <p className="text-muted-foreground text-[11px] leading-relaxed">
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

        {error && <p className="text-destructive text-xs">{error}</p>}

        <Button
          size="sm"
          className="bg-primary text-primary-foreground hover:bg-primary/90 w-full"
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
        cls: "border-success/30 bg-success/10 text-success",
      };
    if (ot === "auth" || (!ot && testResult.ok))
      return {
        label: "401",
        cls: "border-warning/30 bg-warning/10 text-warning",
        title:
          "Callable — placeholder credentials returned 401 (expected during sandbox testing)",
      };
    if (ot === "args")
      return {
        label: "args",
        cls: "border-highlight/30 bg-highlight/10 text-highlight",
        title:
          "Callable — requires arguments not supplied in automated testing",
      };
    if (ot === "error" || !testResult.ok)
      return {
        label: "fail",
        cls: "border-destructive/30 bg-destructive/10 text-destructive",
      };
    return {
      label: "pass",
      cls: "border-success/30 bg-success/10 text-success",
    };
  })();

  return (
    <div className="border-border bg-card hover:border-input overflow-hidden rounded-xl border shadow-sm transition-colors">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <ChevronRightIcon
          className={cn(
            "text-muted-foreground size-3.5 shrink-0 transition-transform",
            expanded && "rotate-90",
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <code className="text-foreground font-mono text-sm font-semibold">
              {tool.name}
            </code>
            <span className="border-border bg-muted text-muted-foreground rounded border px-1.5 py-0.5 text-[10px]">
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
            <p className="text-muted-foreground mt-0.5 line-clamp-1 text-xs">
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
            className="text-muted-foreground hover:bg-muted hover:text-foreground rounded-lg p-1.5"
            title="Re-test"
          >
            <RefreshCwIcon className="size-3.5" />
          </button>
        )}
      </button>
      {expanded && (
        <div className="border-border space-y-2 border-t px-4 py-3">
          {tool.description && (
            <p className="text-muted-foreground text-sm leading-relaxed">
              {tool.description}
            </p>
          )}
          {testResult?.error && (
            <div className="text-destructive border-border bg-card rounded-lg border px-3 py-2 font-mono text-xs">
              {testResult.error}
            </div>
          )}
          {testResult?.output && (
            <div className="border-border bg-card text-foreground rounded-lg border px-3 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap">
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
      <div className="border-border bg-card flex items-center gap-3 border-b px-5 py-3">
        <div className="flex min-w-0 flex-1 items-center gap-2.5">
          <div className="border-border bg-muted flex size-7 shrink-0 items-center justify-center rounded-lg border">
            <BoxIcon className="text-highlight size-3.5" />
          </div>
          <div className="min-w-0">
            <p className="text-foreground truncate text-sm font-semibold">
              {server.name}
            </p>
            <p className="text-muted-foreground text-[10px]">
              {tools_discovered.length} tool
              {tools_discovered.length !== 1 ? "s" : ""} discovered
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="border-border bg-muted text-muted-foreground rounded-lg border px-2.5 py-1 text-xs">
            Sandbox
          </span>
          {errors.length > 0 ? (
            <span className="border-destructive/30 bg-destructive/10 text-destructive flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs">
              <XCircleIcon className="size-3" /> {errors.length} error
              {errors.length !== 1 ? "s" : ""}
            </span>
          ) : (
            <span className="border-success/30 bg-success/10 text-success flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs">
              <CheckCircle2Icon className="size-3" /> 0 errors
            </span>
          )}
          <button
            onClick={() => void handleRetest()}
            disabled={retesting}
            className="text-muted-foreground hover:bg-muted hover:text-foreground rounded-lg p-1.5"
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
        <div className="border-success/30 bg-success flex items-center gap-2.5 border-b px-5 py-2.5">
          <div className="flex size-6 items-center justify-center rounded-full bg-current/20">
            <CheckCircle2Icon className="text-success-foreground size-3.5" />
          </div>
          <span className="text-success-foreground text-sm font-medium">
            Sandbox verified — all tools tested successfully
          </span>
        </div>
      )}
      {dp === "needs_secrets" && (
        <div className="border-warning/30 bg-warning flex items-center gap-2.5 border-b px-5 py-2.5">
          <div className="flex size-6 items-center justify-center rounded-full bg-current/20">
            <KeyIcon className="text-warning-foreground size-3.5" />
          </div>
          <span className="text-warning-foreground text-sm font-medium">
            Needs secrets — add API keys below and re-test
          </span>
        </div>
      )}
      {dp === "failed" && (
        <div className="border-destructive/20 bg-destructive flex items-center gap-3 border-b px-5 py-3">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-current/15">
            <ShieldXIcon className="text-destructive-foreground size-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-destructive-foreground text-sm font-semibold">
              Blocked by Security Scan
            </p>
            <p className="text-destructive-foreground/80 text-[11px]">
              {errors.length} {errors.length === 1 ? "issue" : "issues"}{" "}
              prevented execution
            </p>
          </div>
          <span className="text-destructive-foreground flex items-center gap-1.5 rounded-full bg-current/10 px-3 py-1 text-[11px] font-semibold ring-1 ring-current/20">
            <XCircleIcon className="size-3" />
            {errors.length} {errors.length === 1 ? "error" : "errors"}
          </span>
        </div>
      )}
      {dp === "testing" && (
        <div className="border-warning/30 bg-warning flex items-center gap-2.5 border-b px-5 py-2.5">
          <div className="flex size-6 items-center justify-center rounded-full bg-current/20">
            <ShieldAlertIcon className="text-warning-foreground size-3.5" />
          </div>
          <span className="text-warning-foreground text-sm font-medium">
            Couldn&apos;t verify — server started but no tools found
          </span>
        </div>
      )}

      {/* tool list / error details */}
      <div className="bg-muted flex-1 space-y-4 overflow-y-auto p-4">
        {/* Secrets panel — always shown when secrets are detected */}
        {detected_secret_names.length > 0 && (
          <div className="border-border bg-card overflow-hidden rounded-xl border shadow-sm">
            <div className="border-border flex items-center gap-2 border-b px-4 py-3">
              <KeyIcon className="text-highlight size-3.5" />
              <h3 className="text-foreground text-xs font-semibold">
                API Secrets
              </h3>
              {detected_secret_names.some((k) => !storedInfo.has(k)) && (
                <span className="border-destructive/30 bg-destructive/10 text-destructive ml-auto flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium">
                  <span className="bg-destructive size-1.5 rounded-full" />
                  {
                    detected_secret_names.filter((k) => !storedInfo.has(k))
                      .length
                  }{" "}
                  missing
                </span>
              )}
              {detected_secret_names.every((k) => storedInfo.has(k)) && (
                <span className="border-success/30 bg-success/10 text-success ml-auto flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium">
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
              <span className="text-muted-foreground text-[10px] font-semibold tracking-widest uppercase">
                Tools
              </span>
              <div className="bg-accent h-px flex-1" />
              <span className="text-highlight font-mono text-[10px]">
                {tools_discovered.length}
              </span>
            </div>
            <div className="border-border bg-muted flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2">
              <span className="text-muted-foreground text-[10px]">
                Sandbox uses placeholder credentials —
              </span>
              <span className="flex items-center gap-1 text-[10px]">
                <span className="border-success/30 bg-success/10 text-success rounded-full border px-1.5 py-0.5 text-[10px] font-medium">
                  pass
                </span>
                <span className="text-muted-foreground">real response</span>
              </span>
              <span className="flex items-center gap-1 text-[10px]">
                <span className="border-warning/30 bg-warning/10 text-warning rounded-full border px-1.5 py-0.5 text-[10px] font-medium">
                  401
                </span>
                <span className="text-muted-foreground">
                  callable, real key used at runtime
                </span>
              </span>
              <span className="flex items-center gap-1 text-[10px]">
                <span className="border-highlight/30 bg-highlight/10 text-highlight rounded-full border px-1.5 py-0.5 text-[10px] font-medium">
                  args
                </span>
                <span className="text-muted-foreground">
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
              <div className="border-destructive/40 bg-destructive/10 relative flex size-16 items-center justify-center rounded-2xl border">
                <ShieldXIcon className="text-destructive size-8" />
                <span className="bg-destructive ring-muted-foreground text-destructive-foreground absolute -top-1.5 -right-1.5 flex size-5 items-center justify-center rounded-full text-[10px] font-bold ring-2">
                  {errors.length}
                </span>
              </div>
              <div>
                <h3 className="text-foreground text-base font-semibold">
                  Server blocked by security scan
                </h3>
                <p className="text-muted-foreground mt-0.5 text-sm">
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
                  className="border-border bg-card overflow-hidden rounded-xl border shadow-sm"
                >
                  <div className="border-border bg-destructive/10 flex items-center gap-2.5 border-b px-4 py-2.5">
                    <ShieldAlertIcon className="text-destructive size-3.5 shrink-0" />
                    <span className="text-destructive text-[11px] font-semibold tracking-wider uppercase">
                      {isModelCfgError
                        ? "Configuration Error"
                        : "Security Block"}
                    </span>
                    <span className="bg-destructive/15 text-destructive ring-destructive/30 ml-auto rounded-full px-2 py-0.5 text-[10px] font-medium ring-1">
                      #{i + 1}
                    </span>
                  </div>
                  <div className="px-4 py-3.5">
                    <p className="text-muted-foreground text-sm leading-relaxed">
                      {error}
                    </p>
                    {isModelCfgError && (
                      <div className="border-warning/30 bg-warning/10 mt-3.5 rounded-xl border px-3.5 py-3">
                        <p className="text-warning mb-2 text-xs font-semibold">
                          How to fix
                        </p>
                        <ul className="text-warning/80 space-y-1.5 text-xs leading-relaxed">
                          <li className="flex items-start gap-1.5">
                            <span className="mt-0.5 shrink-0 font-bold">
                              1.
                            </span>
                            <span>
                              Open{" "}
                              <code className="text-warning bg-warning/15 rounded px-1 py-0.5 font-mono text-[11px]">
                                config.yaml
                              </code>{" "}
                              and set{" "}
                              <code className="text-warning bg-warning/15 rounded px-1 py-0.5 font-mono text-[11px]">
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
              className="border-border bg-card text-foreground hover:border-input hover:bg-muted flex w-full items-center justify-center gap-2 rounded-xl border px-4 py-3 text-sm font-medium shadow-sm transition-all disabled:opacity-50"
            >
              <RotateCcwIcon
                className={cn("size-4", retesting && "animate-spin")}
              />
              {retesting ? "Re-testing…" : "Re-test after fixing"}
            </button>
          </div>
        ) : tools_discovered.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <div className="border-border bg-muted flex size-12 items-center justify-center rounded-full border">
              <BoxIcon className="text-muted-foreground size-5" />
            </div>
            <p className="text-muted-foreground text-sm font-medium">
              No tools discovered yet
            </p>
            {dp !== "verified" && (
              <p className="text-muted-foreground text-xs">
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
      <div className="bg-card flex flex-1 flex-col items-center justify-center gap-2">
        <TerminalIcon className="text-muted-foreground size-8" />
        <p className="text-muted-foreground text-sm">No code available</p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      <div className="border-border bg-card w-48 shrink-0 border-r">
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
          <div className="bg-card flex flex-1 items-center justify-center">
            <p className="text-muted-foreground text-sm">Select a file</p>
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
      return next;
    });
    // Check outside the updater — calling parent setState inside an updater is illegal in React
    const required = buildStatus.detected_secret_names;
    const allStored =
      required.length > 0 &&
      required.every((k) => storedInfo.has(k) || k in hints);
    if (allStored) {
      onAllSecretsStored?.();
    }
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
      <div className="border-border flex w-1/2 shrink-0 flex-col border-r">
        {threadId ? (
          <BuildActivityFeed
            messages={stream.messages ?? []}
            isLoading={stream.isLoading}
            onSubmit={handleSubmit}
          />
        ) : (
          <div className="bg-muted flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
            <div className="border-border bg-card flex size-10 items-center justify-center rounded-full border">
              <TerminalIcon className="text-muted-foreground size-4" />
            </div>
            <p className="text-foreground text-sm font-medium">
              No chat session linked
            </p>
            <p className="text-muted-foreground text-xs">
              Create a new server from the Start tab to get an embedded chat.
            </p>
          </div>
        )}
      </div>

      {/* RIGHT: white panel with tabs */}
      <div className="bg-card flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="border-border bg-card flex items-center gap-0 border-b px-5 pt-3">
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
                  ? "text-foreground border-highlight border-b-2"
                  : "text-muted-foreground hover:text-foreground",
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
    <div className="bg-muted flex flex-1 items-center justify-center p-8">
      <div className="w-full max-w-xl space-y-6">
        <div className="space-y-1 text-center">
          <h2 className="text-foreground text-2xl font-semibold">
            What do you want to build?
          </h2>
          <p className="text-muted-foreground text-sm">
            Describe your MCP server and the agent will write and verify it.
          </p>
        </div>

        <div className="space-y-1.5">
          <label className="text-muted-foreground text-xs font-medium">
            Server name <span className="text-destructive">*</span>
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. GitHub Issues Connector"
            className="border-border bg-card text-foreground placeholder:text-muted-foreground focus:border-input focus:ring-foreground/5 w-full rounded-xl border px-3 py-2.5 text-sm shadow-sm focus:ring-2 focus:outline-none"
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-muted-foreground text-xs font-medium">
            Description
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe what this server should do, what APIs it connects to, and what tools it should expose…"
            rows={4}
            className="border-border bg-card text-foreground placeholder:text-muted-foreground focus:border-input focus:ring-foreground/5 w-full resize-none rounded-xl border px-3 py-2.5 text-sm shadow-sm focus:ring-2 focus:outline-none"
          />
        </div>

        <div className="space-y-1.5">
          <p className="text-muted-foreground text-xs font-medium">Template</p>
          <div className="flex flex-wrap gap-2">
            {TEMPLATE_TYPES.map((t) => (
              <button
                key={t.id}
                onClick={() => setTemplate(t.id)}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-xs font-medium transition-all",
                  template === t.id
                    ? "border-primary bg-primary text-primary-foreground shadow-sm"
                    : "border-border bg-card text-muted-foreground hover:border-input hover:shadow-sm",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <p className="border-destructive/30 bg-destructive/10 text-destructive rounded-xl border px-3 py-2 text-xs">
            {error}
          </p>
        )}

        <Button
          onClick={() => void doCreate()}
          disabled={!name.trim() || creating}
          className="bg-primary text-primary-foreground hover:bg-primary/90 w-full shadow-sm"
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

type DeployStep = {
  key: string;
  label: string;
  status: "pending" | "running" | "done" | "failed";
  detail: string | null;
};

function deployProgress(steps: DeployStep[]): number {
  if (steps.length === 0) return 0;
  const doneCount = steps.filter((s) => s.status === "done").length;
  // Non-linear weights: "building" (index 1) takes most of the time
  const thresholds = [5, 20, 80, 95, 100];
  return thresholds[doneCount] ?? 100;
}

function DeployTimeline({
  serverName,
  steps,
}: {
  serverName: string;
  steps: DeployStep[];
}) {
  const progress = deployProgress(steps);
  const current = steps.find((s) => s.status === "running");
  const failed = steps.find((s) => s.status === "failed");

  // SVG ring
  const r = 44;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - progress / 100);

  return (
    <div className="border-border bg-card w-full max-w-sm overflow-hidden rounded-2xl border shadow-sm">
      {/* Header */}
      <div className="border-border border-b px-5 py-4 text-center">
        <p className="text-foreground text-sm font-semibold">
          Deploying {serverName}
        </p>
        <p className="text-muted-foreground mt-0.5 text-[11px]">
          {failed
            ? (failed.detail ?? "Deployment failed")
            : (current?.detail ?? "Please wait…")}
        </p>
      </div>

      {/* Circular progress */}
      <div className="flex flex-col items-center gap-3 px-5 pt-5 pb-3">
        <svg width="110" height="110" viewBox="0 0 110 110">
          <circle
            cx="55"
            cy="55"
            r={r}
            fill="none"
            stroke="var(--color-border)"
            strokeWidth="7"
          />
          <circle
            cx="55"
            cy="55"
            r={r}
            fill="none"
            stroke={
              failed ? "var(--color-destructive)" : "var(--color-highlight)"
            }
            strokeWidth="7"
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={offset}
            transform="rotate(-90 55 55)"
            style={{ transition: "stroke-dashoffset 0.6s ease" }}
          />
          <text
            x="55"
            y="55"
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize="18"
            fontWeight="700"
            fill={
              failed ? "var(--color-destructive)" : "var(--color-foreground)"
            }
          >
            {progress}%
          </text>
        </svg>

        {/* Thin progress bar */}
        <div className="bg-muted h-1 w-full overflow-hidden rounded-full">
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{
              width: `${progress}%`,
              backgroundColor: failed
                ? "var(--color-destructive)"
                : "var(--color-highlight)",
            }}
          />
        </div>
      </div>

      {/* Step list */}
      <div className="flex flex-col gap-1 px-4 pb-4">
        {steps.map((step) => (
          <div
            key={step.key}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors",
              step.status === "running" && "bg-highlight/10",
              step.status === "done" && "bg-success/10",
              step.status === "failed" && "bg-destructive/10",
              step.status === "pending" && "bg-transparent",
            )}
          >
            <div className="shrink-0">
              {step.status === "done" && (
                <CheckCircle2Icon className="text-success size-4" />
              )}
              {step.status === "running" && (
                <Loader2Icon className="text-highlight size-4 animate-spin" />
              )}
              {step.status === "failed" && (
                <XCircleIcon className="text-destructive size-4" />
              )}
              {step.status === "pending" && (
                <div className="border-border size-4 rounded-full border-2" />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p
                className={cn(
                  "text-xs font-medium",
                  step.status === "running" && "text-highlight",
                  step.status === "done" && "text-success",
                  step.status === "failed" && "text-destructive",
                  step.status === "pending" && "text-muted-foreground",
                )}
              >
                {step.label}
              </p>
              {step.status === "running" && step.detail && (
                <p className="text-muted-foreground text-[10px]">
                  {step.detail}
                </p>
              )}
              {step.status === "failed" && step.detail && (
                <p className="text-destructive truncate text-[10px]">
                  {step.detail}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

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
  const [undeploying, setUndeploying] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const phase = buildStatus?.phase ?? server.phase ?? "idle";
  const isVerified = phase === "verified";
  const isDeployed = phase === "deployed";
  const isDeploying = phase === "deploying";
  const isFailed = phase === "failed";
  const toolCount = buildStatus?.tools_discovered.length ?? 0;
  const secretCount = buildStatus?.detected_secret_names.length ?? 0;
  const containerPort = buildStatus?.container_port;
  const sseUrl = containerPort ? `http://localhost:${containerPort}/sse` : null;
  const deploySteps = (buildStatus?.deploy_steps ?? []) as DeployStep[];
  const hasTimeline = isDeploying || (isFailed && deploySteps.length > 0);

  const canDeploy =
    allSecretsStored && (isVerified || isDeployed) && !isDeploying;

  const handleDeploy = async () => {
    setError(null);
    try {
      // #59: approval is given on the Build board, for the code by its hash;
      // this page only turns an already-approved server back on.
      if (!server.approved) {
        setError("Approve it on the Build board first: Connections > Build.");
        return;
      }
      const result = await apiDeploy(server.id);
      onBuildStatusChanged(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deploy failed");
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

  // ── Deploying: show live timeline instead of the checklist ─────────────────
  if (hasTimeline) {
    return (
      <div className="bg-muted flex flex-1 flex-col items-center justify-center gap-4 p-8">
        <DeployTimeline serverName={server.name} steps={deploySteps} />
        {isFailed && (
          <Button
            className="bg-primary text-primary-foreground hover:bg-primary/90 w-full max-w-sm py-3 text-sm font-semibold"
            onClick={() => void handleDeploy()}
          >
            Retry deploy
          </Button>
        )}
        <p className="text-muted-foreground max-w-sm text-center text-[10px] leading-relaxed">
          Secrets are injected as container env vars and are never written to
          disk or logs.
        </p>
      </div>
    );
  }

  // ── Idle / verified / deployed: show the checklist card ────────────────────
  return (
    <div className="bg-muted flex flex-1 flex-col items-center justify-center gap-6 p-8">
      {/* Server card */}
      <div className="border-border bg-card w-full max-w-sm overflow-hidden rounded-2xl border shadow-sm">
        <div className="border-border flex items-center gap-3 border-b px-5 py-4">
          <div className="border-border bg-muted flex size-9 shrink-0 items-center justify-center rounded-xl border">
            <BoxIcon className="text-highlight size-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-foreground truncate text-sm font-semibold">
              {server.name}
            </p>
            <p className="text-muted-foreground text-[10px]">MCP Server</p>
          </div>
          {isDeployed && (
            <span className="border-success/30 bg-success/10 text-success flex items-center gap-1 rounded-full border px-2.5 py-1 text-[10px] font-medium">
              <CheckCircle2Icon className="size-3" /> Live
            </span>
          )}
        </div>

        {/* Checklist */}
        <div className="divide-border divide-y px-5">
          <div className="flex items-center gap-3 py-3">
            {isVerified || isDeployed ? (
              <CheckCircle2Icon className="text-success size-4 shrink-0" />
            ) : (
              <div className="border-border size-4 shrink-0 rounded-full border-2" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-foreground text-xs font-medium">
                Sandbox verified
              </p>
              <p className="text-muted-foreground text-[10px]">
                {toolCount} tool{toolCount !== 1 ? "s" : ""} discovered &amp;
                tested
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 py-3">
            {allSecretsStored ? (
              <CheckCircle2Icon className="text-success size-4 shrink-0" />
            ) : (
              <div className="border-warning/30 size-4 shrink-0 rounded-full border-2" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-foreground text-xs font-medium">
                API secrets stored
              </p>
              <p className="text-muted-foreground text-[10px]">
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
              <CheckCircle2Icon className="text-success size-4 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-foreground text-xs font-medium">
                  Running on port {containerPort}
                </p>
                <p className="text-muted-foreground text-[10px]">
                  Docker container · SSE transport
                </p>
              </div>
            </div>
          )}
        </div>

        {/* SSE URL */}
        {isDeployed && sseUrl && (
          <div className="border-border border-t px-5 py-3">
            <p className="text-muted-foreground mb-1.5 text-[10px] font-semibold tracking-wider uppercase">
              SSE endpoint
            </p>
            <div className="border-border bg-muted flex items-center gap-2 rounded-lg border px-3 py-2">
              <code className="text-foreground min-w-0 flex-1 truncate font-mono text-[11px]">
                {sseUrl}
              </code>
              <button
                onClick={copyUrl}
                className="text-muted-foreground hover:text-foreground shrink-0"
                title="Copy URL"
              >
                {copied ? (
                  <CheckIcon className="text-success size-3.5" />
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
                ? "bg-primary text-primary-foreground hover:bg-primary/90"
                : "bg-muted text-muted-foreground cursor-not-allowed",
            )}
            disabled={!canDeploy}
            onClick={() => void handleDeploy()}
          >
            {server.approved
              ? "Deploy to Docker"
              : "Approve on the Build board"}
          </Button>
        ) : (
          <div className="flex flex-col gap-2">
            <Button
              className="border-border bg-card text-foreground hover:bg-muted w-full border py-3 text-sm font-semibold shadow-sm"
              onClick={() => void handleDeploy()}
            >
              Re-deploy
            </Button>
            <Button
              className="border-destructive/30 bg-destructive/10 text-destructive hover:bg-destructive/15 w-full border py-3 text-sm font-semibold"
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
          <p className="text-muted-foreground text-center text-[11px]">
            Add your API secrets on the Build tab to enable deploy
          </p>
        )}
        {allSecretsStored && !isVerified && !isDeployed && (
          <p className="text-muted-foreground text-center text-[11px]">
            Run the sandbox test on the Build tab to reach verified phase
          </p>
        )}
        {isDeployed && (
          <p className="text-muted-foreground text-center text-[11px]">
            Go to the Connect tab to wire this server into the agent
          </p>
        )}
        {error && (
          <p className="text-destructive text-center text-xs">{error}</p>
        )}
      </div>

      {/* Docker note */}
      <p className="text-muted-foreground max-w-sm text-center text-[10px] leading-relaxed">
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
      <div className="bg-muted flex flex-1 flex-col items-center justify-center gap-4 p-8">
        <div className="border-border bg-card flex size-14 items-center justify-center rounded-2xl border shadow-sm">
          <PlugIcon className="text-muted-foreground size-6" />
        </div>
        <div className="space-y-1 text-center">
          <p className="text-foreground text-sm font-medium">
            Deploy first to connect
          </p>
          <p className="text-muted-foreground text-xs">
            The server needs to be running in Docker before it can be wired into
            the agent.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-muted flex flex-1 flex-col items-center justify-center gap-6 p-8">
      <div className="border-border bg-card w-full max-w-sm overflow-hidden rounded-2xl border shadow-sm">
        {/* Header */}
        <div className="border-border flex items-center gap-3 border-b px-5 py-4">
          <div className="border-border bg-muted flex size-9 shrink-0 items-center justify-center rounded-xl border">
            <PlugZapIcon className="text-highlight size-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-foreground truncate text-sm font-semibold">
              {server.name}
            </p>
            <p className="text-muted-foreground text-[10px]">
              Running · port {containerPort}
            </p>
          </div>
          {connected && (
            <span className="border-success/30 bg-success/10 text-success flex items-center gap-1 rounded-full border px-2.5 py-1 text-[10px] font-medium">
              <CheckCircle2Icon className="size-3" /> Wired in
            </span>
          )}
        </div>

        {/* SSE URL row */}
        {sseUrl && (
          <div className="px-5 py-3">
            <p className="text-muted-foreground mb-1.5 text-[10px] font-semibold tracking-wider uppercase">
              SSE endpoint
            </p>
            <div className="border-border bg-muted flex items-center gap-2 rounded-lg border px-3 py-2">
              <code className="text-foreground min-w-0 flex-1 truncate font-mono text-[11px]">
                {sseUrl}
              </code>
              <button
                onClick={copyUrl}
                className="text-muted-foreground hover:text-foreground shrink-0"
                title="Copy"
              >
                {copied ? (
                  <CheckIcon className="text-success size-3.5" />
                ) : (
                  <CopyIcon className="size-3.5" />
                )}
              </button>
            </div>
          </div>
        )}

        {/* After connect: show what was registered */}
        {connected && connectedName && (
          <div className="border-border border-t px-5 py-3">
            <p className="text-muted-foreground text-[10px] leading-relaxed">
              Added{" "}
              <code className="bg-muted text-foreground rounded px-1 py-0.5 font-mono text-[10px]">
                {connectedName}
              </code>{" "}
              to{" "}
              <code className="bg-muted text-foreground rounded px-1 py-0.5 font-mono text-[10px]">
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
              ? "border-success/30 bg-success/10 text-success hover:bg-success/15 border"
              : "bg-primary text-primary-foreground hover:bg-primary/90",
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

        {error && (
          <p className="text-destructive text-center text-xs">{error}</p>
        )}
      </div>

      <p className="text-muted-foreground max-w-sm text-center text-[10px] leading-relaxed">
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
        <Loader2Icon className="text-muted-foreground size-5 animate-spin" />
      </div>
    );
  }

  if (!isNew && loadError) {
    return (
      <div className="flex size-full flex-col items-center justify-center gap-3">
        <XCircleIcon className="text-destructive size-8" />
        <p className="text-muted-foreground text-sm">{loadError}</p>
        <Link
          href="/workspace/mcp"
          className="text-muted-foreground hover:text-foreground text-xs underline"
        >
          Back to MCP Suite
        </Link>
      </div>
    );
  }

  return (
    <div className="bg-card flex size-full flex-col overflow-hidden">
      {/* Header */}
      <div className="border-border bg-card flex items-center gap-3 border-b px-5 py-3.5">
        <Link
          href="/workspace/mcp"
          className="text-muted-foreground hover:bg-muted hover:text-foreground rounded-lg p-1.5"
        >
          <ArrowLeftIcon className="size-4" />
        </Link>
        <div className="min-w-0 flex-1">
          <p className="text-muted-foreground text-[10px] font-semibold tracking-widest uppercase">
            MCP Studio
          </p>
          <h1 className="text-foreground truncate text-base font-semibold">
            {isNew ? "New MCP Server" : (server?.name ?? "Loading…")}
          </h1>
        </div>
        {!isNew && <PhasePill phase={phase} errors={errors} />}
      </div>

      {/* Lifecycle tab bar */}
      <div className="border-border bg-card flex items-center gap-0 border-b px-5 pt-3">
        {LIFECYCLE_TABS.map(({ id, label, disabled }) => (
          <button
            key={id}
            onClick={() => !disabled && setActiveTab(id)}
            disabled={disabled}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors",
              disabled
                ? "text-muted-foreground cursor-not-allowed"
                : activeTab === id
                  ? "border-foreground text-foreground border-b-2"
                  : "text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
            {disabled && <LockIcon className="text-muted-foreground size-3" />}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {activeTab === "start" && isNew && (
          <StartTab onCreated={handleCreated} />
        )}
        {activeTab === "start" && !isNew && (
          <div className="bg-muted flex flex-1 items-center justify-center p-8">
            <div className="space-y-3 text-center">
              <p className="text-muted-foreground text-sm">
                This server was already created.
              </p>
              <Button
                size="sm"
                className="bg-primary text-primary-foreground hover:bg-primary/90"
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
            <div className="bg-muted flex flex-1 items-center justify-center">
              <p className="text-muted-foreground text-sm">
                No build data yet.
              </p>
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
