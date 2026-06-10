import {
  ActivityIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  Code2Icon,
  CopyIcon,
  DownloadIcon,
  EyeIcon,
  FileIcon,
  FolderIcon,
  FolderOpenIcon,
  FolderTreeIcon,
  LoaderIcon,
  PackageIcon,
  PlayIcon,
  RotateCcwIcon,
  SquareArrowOutUpRightIcon,
  SquareIcon,
  XIcon,
} from "lucide-react";
import {
  Component,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { toast } from "sonner";
import { Streamdown } from "streamdown";

import {
  Artifact,
  ArtifactAction,
  ArtifactActions,
  ArtifactContent,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectItem } from "@/components/ui/select";
import {
  SelectContent,
  SelectGroup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CodeEditor } from "@/components/workspace/code-editor";
import type { ArtifactManifest, ProjectFileEntry } from "@/core/artifacts/api";
import {
  useArtifactContent,
  useArtifactManifests,
  useCreatePreviewFromManifest,
  usePreviewSessionLogs,
  usePreviewSessions,
  useProjectFileContent,
  useProjectFiles,
  useRestartPreviewSession,
  useStopPreviewSession,
  useWorkspaceFileContent,
  useWorkspaceFiles,
} from "@/core/artifacts/hooks";
import {
  artifactDisplayName,
  normalizeArtifactEntries,
  parseArtifactManifestValue,
  urlOfArtifact,
  urlOfArtifactPreview,
} from "@/core/artifacts/utils";
import { useI18n } from "@/core/i18n/hooks";
import { installSkill } from "@/core/skills/api";
import { streamdownPlugins } from "@/core/streamdown";
import { checkCodeFile, getFileName } from "@/core/utils/files";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { ArtifactLink } from "../citations/artifact-link";
import { useThread } from "../messages/context";
import { Tooltip } from "../tooltip";

import { useArtifacts } from "./context";

class ArtifactErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <Artifact>
          <ArtifactContent className="flex items-center justify-center p-6 text-center">
            <div className="text-muted-foreground max-w-sm text-sm">
              Failed to render artifact.{" "}
              <span className="text-destructive font-mono text-xs">
                {this.state.error.message}
              </span>
            </div>
          </ArtifactContent>
        </Artifact>
      );
    }
    return this.props.children;
  }
}

function ArtifactFileDetailInner({
  className,
  filepath: filepathFromProps,
  threadId,
}: {
  className?: string;
  filepath: string;
  threadId: string;
}) {
  const { t } = useI18n();
  const { artifacts, setOpen, select } = useArtifacts();
  const { manifests } = useArtifactManifests({ threadId });
  const normalizedArtifacts = useMemo(() => {
    return normalizeArtifactEntries(artifacts ?? []);
  }, [artifacts]);
  const manifestId = useMemo(() => {
    return parseArtifactManifestValue(filepathFromProps);
  }, [filepathFromProps]);
  const manifest = useMemo(() => {
    return manifestId
      ? manifests.find((candidate) => candidate.id === manifestId)
      : undefined;
  }, [manifestId, manifests]);
  const isWriteFile = useMemo(() => {
    return filepathFromProps.startsWith("write-file:");
  }, [filepathFromProps]);
  const isDynamicManifest = manifest?.preview.mode === "dev_server";
  const filepath = useMemo(() => {
    if (manifest) {
      return manifest.entrypoint_path ?? manifest.manifest_path;
    }
    if (isWriteFile) {
      const url = new URL(filepathFromProps);
      return decodeURIComponent(url.pathname);
    }
    return filepathFromProps;
  }, [filepathFromProps, isWriteFile, manifest]);
  const isSkillFile = useMemo(() => {
    return filepath.endsWith(".skill");
  }, [filepath]);
  const { isCodeFile, language } = useMemo(() => {
    if (isWriteFile) {
      let language = checkCodeFile(filepath).language;
      language ??= "text";
      return { isCodeFile: true, language };
    }
    // Treat .skill files as markdown (they contain SKILL.md)
    if (isSkillFile) {
      return { isCodeFile: true, language: "markdown" };
    }
    return checkCodeFile(filepath);
  }, [filepath, isWriteFile, isSkillFile]);
  const isSupportPreview = useMemo(() => {
    return (
      !isDynamicManifest && (language === "html" || language === "markdown")
    );
  }, [isDynamicManifest, language]);

  // Extract workspace project root from write-file paths like /mnt/user-data/workspace/project-name/...
  const workspaceProjectRoot = useMemo(() => {
    if (!isWriteFile) return null;
    try {
      const url = new URL(filepathFromProps);
      const filePath = decodeURIComponent(url.pathname);
      const match = /^\/mnt\/user-data\/workspace\/([^/]+)/.exec(filePath);
      return match?.[1] ?? null;
    } catch {
      return null;
    }
  }, [isWriteFile, filepathFromProps]);

  // Determine if this artifact has a project tree (manifest or workspace)
  const hasProjectTree = Boolean(manifest ?? workspaceProjectRoot);
  const { content } = useArtifactContent({
    threadId,
    filepath: manifest?.entrypoint_path ?? filepathFromProps,
    enabled:
      !isDynamicManifest &&
      isCodeFile &&
      !isWriteFile &&
      (!manifestId || Boolean(manifest)),
  });
  const { isMock } = useThread();
  const { previews } = usePreviewSessions({
    threadId,
    enabled: Boolean(isDynamicManifest),
  });
  const createPreviewFromManifest = useCreatePreviewFromManifest({ threadId });
  const stopPreview = useStopPreviewSession({ threadId });
  const restartPreview = useRestartPreviewSession({ threadId });
  const previewSession = useMemo(() => {
    if (!manifestId) {
      return undefined;
    }
    return previews.find((preview) => preview.artifact_id === manifestId);
  }, [manifestId, previews]);
  const { logs: previewLogs } = usePreviewSessionLogs({
    threadId,
    previewId: previewSession?.id,
    enabled: Boolean(previewSession),
  });

  const displayContent = content ?? "";
  const previewUrl = useMemo(() => {
    if (isDynamicManifest) {
      return previewSession?.proxy_url;
    }
    if (isWriteFile || language !== "html") {
      return undefined;
    }
    return urlOfArtifactPreview({ filepath, threadId, isMock });
  }, [
    filepath,
    isDynamicManifest,
    isMock,
    isWriteFile,
    language,
    previewSession?.proxy_url,
    threadId,
  ]);

  const [viewMode, setViewMode] = useState<
    "code" | "preview" | "logs" | "files"
  >("code");
  const [isInstalling, setIsInstalling] = useState(false);
  const [previewReloadKey, setPreviewReloadKey] = useState(0);
  const [previewCreateError, setPreviewCreateError] = useState<string | null>(
    null,
  );

  useEffect(() => {
    if (hasProjectTree) {
      setViewMode("files");
      return;
    }
    if (isSupportPreview) {
      setViewMode("preview");
    } else {
      setViewMode("code");
    }
  }, [hasProjectTree, isSupportPreview]);

  // Clear inline create error when switching to a different artifact
  useEffect(() => {
    setPreviewCreateError(null);
  }, [manifestId]);

  const handleInstallSkill = useCallback(async () => {
    if (isInstalling) return;

    setIsInstalling(true);
    try {
      const result = await installSkill({
        thread_id: threadId,
        path: filepath,
      });
      if (result.success) {
        toast.success(result.message);
      } else {
        toast.error(result.message ?? "Failed to install skill");
      }
    } catch (error) {
      console.error("Failed to install skill:", error);
      toast.error("Failed to install skill");
    } finally {
      setIsInstalling(false);
    }
  }, [threadId, filepath, isInstalling]);

  const handleRestartPreview = useCallback(async () => {
    setPreviewCreateError(null);
    if (!previewSession) {
      if (!manifestId) return;
      try {
        await createPreviewFromManifest.mutateAsync({
          threadId,
          artifactId: manifestId,
        });
        setPreviewReloadKey((value) => value + 1);
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Failed to start live preview session";
        setPreviewCreateError(message);
        toast.error(message);
      }
      return;
    }

    try {
      await restartPreview.mutateAsync({
        threadId,
        previewId: previewSession.id,
      });
      setPreviewReloadKey((value) => value + 1);
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to restart live preview session";
      // Session or sandbox no longer exists (e.g. server restarted) — create a fresh one
      const isGone =
        message.includes("404") ||
        message.toLowerCase().includes("not found") ||
        message.toLowerCase().includes("no longer available");
      if (manifestId && isGone) {
        try {
          await createPreviewFromManifest.mutateAsync({
            threadId,
            artifactId: manifestId,
          });
          setPreviewReloadKey((v) => v + 1);
          return;
        } catch {
          // fall through and show the original restart error
        }
      }
      setPreviewCreateError(message);
      toast.error(message);
    }
  }, [
    createPreviewFromManifest,
    manifestId,
    previewSession,
    restartPreview,
    threadId,
  ]);

  const handleStopPreview = useCallback(async () => {
    if (!previewSession) {
      return;
    }
    try {
      await stopPreview.mutateAsync({
        threadId,
        previewId: previewSession.id,
      });
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "Failed to stop live preview session",
      );
    }
  }, [previewSession, stopPreview, threadId]);

  return (
    <Artifact className={cn(className)}>
      <ArtifactHeader className="gap-1 px-2">
        <div className="flex min-w-0 shrink items-center gap-1 overflow-hidden">
          <ArtifactTitle className="min-w-0 overflow-hidden">
            {isWriteFile ? (
              <div className="truncate px-2 text-sm">
                {getFileName(filepath)}
              </div>
            ) : (
              <Select value={filepathFromProps} onValueChange={select}>
                <SelectTrigger className="max-w-40 min-w-0 truncate border-none bg-transparent! shadow-none select-none focus:outline-0 active:outline-0">
                  <SelectValue placeholder="Select a file" />
                </SelectTrigger>
                <SelectContent className="select-none">
                  <SelectGroup>
                    {normalizedArtifacts.map((artifact) => (
                      <SelectItem key={artifact} value={artifact}>
                        {artifactDisplayName(artifact, manifests, getFileName)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            )}
          </ArtifactTitle>
          {isDynamicManifest && (
            <Badge
              variant="secondary"
              className="hidden shrink-0 rounded text-[10px] sm:flex"
            >
              <ActivityIcon className="mr-1 size-3" />
              {previewSession?.status ??
                (createPreviewFromManifest.isPending
                  ? "starting"
                  : "not running")}
            </Badge>
          )}
        </div>
        <div className="flex shrink-0 items-center justify-center">
          {isDynamicManifest && (
            <ToggleGroup
              className="mx-auto"
              type="single"
              variant="outline"
              size="sm"
              value={viewMode}
              onValueChange={(value) => {
                if (value) {
                  setViewMode(value as "preview" | "logs" | "files");
                }
              }}
            >
              <ToggleGroupItem value="preview">
                <EyeIcon />
              </ToggleGroupItem>
              <ToggleGroupItem value="logs">
                <ActivityIcon />
              </ToggleGroupItem>
              <ToggleGroupItem value="files">
                <FolderTreeIcon />
              </ToggleGroupItem>
            </ToggleGroup>
          )}
          {!isDynamicManifest && (isSupportPreview || manifest) && (
            <ToggleGroup
              className="mx-auto"
              type="single"
              variant="outline"
              size="sm"
              value={viewMode}
              onValueChange={(value) => {
                if (value) {
                  setViewMode(value as "code" | "preview" | "files");
                }
              }}
            >
              {isCodeFile && (
                <ToggleGroupItem value="code">
                  <Code2Icon />
                </ToggleGroupItem>
              )}
              {isSupportPreview && (
                <ToggleGroupItem value="preview">
                  <EyeIcon />
                </ToggleGroupItem>
              )}
              {manifest && (
                <ToggleGroupItem value="files">
                  <FolderTreeIcon />
                </ToggleGroupItem>
              )}
            </ToggleGroup>
          )}
          {isWriteFile && workspaceProjectRoot && (
            <ToggleGroup
              className="mx-auto"
              type="single"
              variant="outline"
              size="sm"
              value={viewMode}
              onValueChange={(value) => {
                if (value) {
                  setViewMode(value as "code" | "files");
                }
              }}
            >
              <ToggleGroupItem value="code">
                <Code2Icon />
              </ToggleGroupItem>
              <ToggleGroupItem value="files">
                <FolderTreeIcon />
              </ToggleGroupItem>
            </ToggleGroup>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <ArtifactActions>
            {!isWriteFile && filepath.endsWith(".skill") && (
              <Tooltip content={t.toolCalls.skillInstallTooltip}>
                <ArtifactAction
                  icon={isInstalling ? LoaderIcon : PackageIcon}
                  label={t.common.install}
                  tooltip={t.common.install}
                  disabled={
                    isInstalling ||
                    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
                  }
                  onClick={handleInstallSkill}
                />
              </Tooltip>
            )}
            {!isWriteFile && (
              <ArtifactAction
                icon={SquareArrowOutUpRightIcon}
                label={t.common.openInNewWindow}
                tooltip={t.common.openInNewWindow}
                onClick={() => {
                  const targetUrl =
                    previewUrl ??
                    urlOfArtifact({
                      filepath,
                      threadId,
                      isMock,
                    });
                  const w = window.open(
                    targetUrl,
                    "_blank",
                    "noopener,noreferrer",
                  );
                  if (w) w.opener = null;
                }}
              />
            )}
            {isDynamicManifest && (
              <>
                <ArtifactAction
                  icon={previewSession ? RotateCcwIcon : PlayIcon}
                  label={previewSession ? "Restart preview" : "Start preview"}
                  tooltip={previewSession ? "Restart preview" : "Start preview"}
                  disabled={
                    createPreviewFromManifest.isPending ||
                    restartPreview.isPending
                  }
                  onClick={() => {
                    void handleRestartPreview();
                  }}
                />
                <ArtifactAction
                  icon={SquareIcon}
                  label="Stop preview"
                  tooltip="Stop preview"
                  disabled={!previewSession || stopPreview.isPending}
                  onClick={() => {
                    void handleStopPreview();
                  }}
                />
              </>
            )}
            {!isDynamicManifest && isCodeFile && (
              <ArtifactAction
                icon={CopyIcon}
                label={t.clipboard.copyToClipboard}
                disabled={!content}
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(displayContent ?? "");
                    toast.success(t.clipboard.copiedToClipboard);
                  } catch (error) {
                    toast.error("Failed to copy to clipboard");
                    console.error(error);
                  }
                }}
                tooltip={t.clipboard.copyToClipboard}
              />
            )}
            {!isWriteFile && (
              <ArtifactAction
                icon={DownloadIcon}
                label={t.common.download}
                tooltip={t.common.download}
                onClick={() => {
                  const w = window.open(
                    urlOfArtifact({
                      filepath,
                      threadId,
                      download: true,
                      isMock,
                    }),
                    "_blank",
                    "noopener,noreferrer",
                  );
                  if (w) w.opener = null;
                }}
              />
            )}
            <ArtifactAction
              icon={XIcon}
              label={t.common.close}
              onClick={() => setOpen(false)}
              tooltip={t.common.close}
            />
          </ArtifactActions>
        </div>
      </ArtifactHeader>
      <ArtifactContent className="p-0">
        {isDynamicManifest && manifest && viewMode === "files" && (
          <ProjectFilesPanel artifactId={manifest.id} threadId={threadId} />
        )}
        {isDynamicManifest && manifest && viewMode !== "files" && (
          <DynamicArtifactPreviewPanel
            key={`${previewSession?.id ?? "preview"}-${previewReloadKey}`}
            manifest={manifest}
            previewUrl={previewUrl}
            previewStatus={previewSession?.status}
            previewError={previewSession?.error}
            previewCreateError={previewCreateError}
            isCreating={createPreviewFromManifest.isPending}
            logs={previewLogs?.logs ?? ""}
            logsStatus={previewLogs?.status ?? previewSession?.status}
            viewMode={viewMode}
            onStartPreview={() => {
              void handleRestartPreview();
            }}
          />
        )}
        {!isDynamicManifest && viewMode === "files" && manifest && (
          <ProjectFilesPanel artifactId={manifest.id} threadId={threadId} />
        )}
        {isWriteFile &&
          viewMode === "files" &&
          workspaceProjectRoot &&
          !manifest && (
            <ProjectFilesPanel
              threadId={threadId}
              workspaceRoot={workspaceProjectRoot}
            />
          )}
        {!isDynamicManifest &&
          isSupportPreview &&
          viewMode === "preview" &&
          (language === "markdown" || language === "html") && (
            <ArtifactFilePreview
              content={displayContent}
              language={language ?? "text"}
              previewUrl={previewUrl}
            />
          )}
        {!isDynamicManifest && isCodeFile && viewMode === "code" && (
          <CodeEditor
            className="size-full resize-none rounded-none border-none"
            value={displayContent ?? ""}
            readonly
          />
        )}
        {!isDynamicManifest && !isCodeFile && (
          <iframe
            className="size-full"
            src={urlOfArtifact({ filepath, threadId, isMock })}
          />
        )}
      </ArtifactContent>
    </Artifact>
  );
}

export function ArtifactFileDetail({
  className,
  filepath,
  threadId,
}: {
  className?: string;
  filepath: string;
  threadId: string;
}) {
  return (
    <ArtifactErrorBoundary>
      <ArtifactFileDetailInner
        className={className}
        filepath={filepath}
        threadId={threadId}
      />
    </ArtifactErrorBoundary>
  );
}

function DynamicArtifactPreviewPanel({
  manifest,
  previewUrl,
  previewStatus,
  previewError,
  previewCreateError,
  isCreating,
  logs,
  logsStatus,
  viewMode,
  onStartPreview,
}: {
  manifest: ArtifactManifest;
  previewUrl?: string;
  previewStatus?: "starting" | "running" | "failed" | "stopped";
  previewError?: string | null;
  previewCreateError?: string | null;
  isCreating?: boolean;
  logs: string;
  logsStatus?: "starting" | "running" | "failed" | "stopped";
  viewMode: "code" | "preview" | "logs";
  onStartPreview: () => void;
}) {
  if (viewMode === "logs") {
    return (
      <div className="bg-background flex size-full flex-col">
        <div className="border-border/60 flex items-center justify-between border-b px-4 py-2">
          <div className="text-sm font-medium">Preview Logs</div>
          <Badge variant="secondary" className="rounded text-[10px]">
            {logsStatus ?? previewStatus ?? "not running"}
          </Badge>
        </div>
        <pre className="bg-muted/20 text-foreground size-full overflow-auto p-4 font-mono text-xs whitespace-pre-wrap">
          {logs || "Waiting for preview logs..."}
        </pre>
      </div>
    );
  }

  // Only show the live preview iframe when the server is confirmed running
  if (previewStatus === "running" && previewUrl) {
    return (
      <iframe
        key={previewUrl}
        className="size-full"
        src={previewUrl}
        title={manifest.title}
      />
    );
  }

  const errorMessage =
    previewCreateError ?? (previewStatus === "failed" ? previewError : null);
  const canStart =
    !previewStatus || previewStatus === "stopped" || previewStatus === "failed";

  return (
    <div className="flex size-full flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="text-sm font-medium">{manifest.title}</div>
      <Badge variant="secondary" className="rounded text-[10px]">
        {isCreating ? "starting" : (previewStatus ?? "not running")}
      </Badge>

      {previewStatus === "starting" && !isCreating && (
        <div className="text-muted-foreground max-w-md text-sm">
          Dev server is starting. Switch to Logs to watch the output.
        </div>
      )}

      {errorMessage && (
        <div className="bg-destructive/10 border-destructive/20 text-destructive max-w-md rounded border p-3 text-left font-mono text-xs break-all whitespace-pre-wrap">
          {errorMessage}
        </div>
      )}

      {canStart && (
        <Button
          size="sm"
          variant="outline"
          disabled={isCreating}
          onClick={onStartPreview}
        >
          {isCreating ? (
            <>
              <LoaderIcon className="animate-spin" />
              Starting...
            </>
          ) : previewStatus ? (
            "Restart Preview"
          ) : (
            "Start Preview"
          )}
        </Button>
      )}
    </div>
  );
}

type FileTreeNode = {
  name: string;
  path: string;
  type: "file" | "dir";
  children: FileTreeNode[];
  size?: number | null;
};

function buildFileTree(files: ProjectFileEntry[]): FileTreeNode[] {
  const root: FileTreeNode[] = [];
  const dirMap = new Map<string, FileTreeNode>();

  const ensureDir = (parts: string[], depth: number): FileTreeNode[] => {
    if (depth === 0) return root;
    const path = parts.slice(0, depth).join("/");
    const existing = dirMap.get(path);
    if (existing) return existing.children;
    const parentChildren = ensureDir(parts, depth - 1);
    const node: FileTreeNode = {
      name: parts[depth - 1] ?? "",
      path,
      type: "dir",
      children: [],
    };
    dirMap.set(path, node);
    parentChildren.push(node);
    return node.children;
  };

  for (const file of files) {
    const parts = file.path.split("/");
    const parentChildren = ensureDir(parts, parts.length - 1);
    parentChildren.push({
      name: parts[parts.length - 1] ?? file.path,
      path: file.path,
      type: file.type,
      children: [],
      size: file.size,
    });
  }

  return root;
}

function FileTreeNodeItem({
  node,
  selectedPath,
  onSelect,
  depth,
}: {
  node: FileTreeNode;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  depth: number;
}) {
  const [isOpen, setIsOpen] = useState(true);
  const indent = depth * 12;

  if (node.type === "dir") {
    return (
      <div>
        <button
          className="hover:bg-muted/50 flex w-full items-center gap-1 rounded px-1 py-0.5 text-left text-xs"
          style={{ paddingLeft: `${indent + 4}px` }}
          onClick={() => setIsOpen((v) => !v)}
        >
          {isOpen ? (
            <ChevronDownIcon className="size-3 shrink-0 opacity-50" />
          ) : (
            <ChevronRightIcon className="size-3 shrink-0 opacity-50" />
          )}
          {isOpen ? (
            <FolderOpenIcon className="text-muted-foreground size-3 shrink-0" />
          ) : (
            <FolderIcon className="text-muted-foreground size-3 shrink-0" />
          )}
          <span className="truncate">{node.name}</span>
        </button>
        {isOpen &&
          node.children.map((child) => (
            <FileTreeNodeItem
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

  return (
    <button
      className={cn(
        "hover:bg-muted/50 flex w-full items-center gap-1 rounded px-1 py-0.5 text-left text-xs",
        selectedPath === node.path && "bg-muted",
      )}
      style={{ paddingLeft: `${indent + 20}px` }}
      onClick={() => onSelect(node.path)}
    >
      <FileIcon className="text-muted-foreground size-3 shrink-0" />
      <span className="truncate">{node.name}</span>
    </button>
  );
}

function ProjectFilesPanel({
  threadId,
  artifactId,
  workspaceRoot,
}: {
  threadId: string;
  artifactId?: string;
  workspaceRoot?: string;
}) {
  const useWorkspace = !artifactId && Boolean(workspaceRoot);

  const manifestFiles = useProjectFiles({
    threadId,
    artifactId: artifactId ?? "",
    enabled: !useWorkspace,
  });

  const wsFiles = useWorkspaceFiles({
    threadId,
    root: workspaceRoot ?? "",
    enabled: useWorkspace,
  });

  const { files, isLoading } = useWorkspace ? wsFiles : manifestFiles;

  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  const manifestContent = useProjectFileContent({
    threadId,
    artifactId: artifactId ?? "",
    path: selectedFile ?? undefined,
    enabled: !useWorkspace && Boolean(selectedFile),
  });

  const wsContent = useWorkspaceFileContent({
    threadId,
    root: workspaceRoot ?? "",
    path: selectedFile ?? undefined,
    enabled: useWorkspace && Boolean(selectedFile),
  });

  const { content, isLoading: isContentLoading } = useWorkspace
    ? wsContent
    : manifestContent;

  const tree = useMemo(() => buildFileTree(files), [files]);

  return (
    <div className="flex size-full overflow-hidden">
      <div className="border-border/60 flex w-48 shrink-0 flex-col overflow-y-auto border-r p-1">
        {isLoading && !files.length ? (
          <div className="text-muted-foreground flex items-center gap-2 px-2 py-2 text-xs">
            <LoaderIcon className="size-3 animate-spin" />
            Loading…
          </div>
        ) : tree.length === 0 ? (
          <div className="text-muted-foreground px-2 py-2 text-xs">
            No files yet
          </div>
        ) : (
          tree.map((node) => (
            <FileTreeNodeItem
              key={node.path}
              node={node}
              selectedPath={selectedFile}
              onSelect={setSelectedFile}
              depth={0}
            />
          ))
        )}
      </div>
      <div className="min-w-0 flex-1 overflow-hidden">
        {selectedFile ? (
          isContentLoading ? (
            <div className="flex size-full items-center justify-center">
              <LoaderIcon className="size-4 animate-spin" />
            </div>
          ) : (
            <CodeEditor
              className="size-full resize-none rounded-none border-none"
              value={content ?? ""}
              readonly
            />
          )
        ) : (
          <div className="text-muted-foreground flex size-full items-center justify-center text-sm">
            Select a file to view its content
          </div>
        )}
      </div>
    </div>
  );
}

export function ArtifactFilePreview({
  content,
  language,
  previewUrl,
}: {
  content: string;
  language: string;
  previewUrl?: string;
}) {
  const [fallbackHtmlPreviewUrl, setFallbackHtmlPreviewUrl] =
    useState<string>();

  useEffect(() => {
    if (language !== "html" || previewUrl) {
      setFallbackHtmlPreviewUrl(undefined);
      return;
    }

    const blob = new Blob([content ?? ""], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    setFallbackHtmlPreviewUrl(url);

    return () => {
      URL.revokeObjectURL(url);
    };
  }, [content, language, previewUrl]);

  if (language === "markdown") {
    return (
      <div className="size-full px-4">
        <Streamdown
          className="size-full"
          {...streamdownPlugins}
          components={{ a: ArtifactLink }}
        >
          {content ?? ""}
        </Streamdown>
      </div>
    );
  }
  if (language === "html") {
    return (
      <iframe
        className="size-full"
        title="Artifact preview"
        sandbox="allow-scripts allow-forms"
        src={previewUrl ?? fallbackHtmlPreviewUrl}
      />
    );
  }
  return null;
}
