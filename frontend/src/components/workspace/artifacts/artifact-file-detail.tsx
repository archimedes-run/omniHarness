import {
  ActivityIcon,
  Code2Icon,
  CopyIcon,
  DownloadIcon,
  EyeIcon,
  LoaderIcon,
  PackageIcon,
  PlayIcon,
  RotateCcwIcon,
  SquareArrowOutUpRightIcon,
  SquareIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
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
import { Select, SelectItem } from "@/components/ui/select";
import {
  SelectContent,
  SelectGroup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CodeEditor } from "@/components/workspace/code-editor";
import type { ArtifactManifest } from "@/core/artifacts/api";
import {
  useArtifactContent,
  useArtifactManifests,
  useCreatePreviewSession,
  usePreviewSessionLogs,
  usePreviewSessions,
  useRestartPreviewSession,
  useStopPreviewSession,
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

export function ArtifactFileDetail({
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
  const dynamicPreviewConfig = useMemo(() => {
    return manifest?.preview.mode === "dev_server"
      ? manifest.preview
      : undefined;
  }, [manifest]);
  const isDynamicManifest = dynamicPreviewConfig !== undefined;
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
  const createPreview = useCreatePreviewSession({ threadId });
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

  const [viewMode, setViewMode] = useState<"code" | "preview" | "logs">("code");
  const [isInstalling, setIsInstalling] = useState(false);
  const [previewReloadKey, setPreviewReloadKey] = useState(0);
  useEffect(() => {
    if (isDynamicManifest) {
      setViewMode("preview");
      return;
    }
    if (isSupportPreview) {
      setViewMode("preview");
    } else {
      setViewMode("code");
    }
  }, [isDynamicManifest, isSupportPreview]);

  useEffect(() => {
    if (
      !manifestId ||
      !manifest ||
      !dynamicPreviewConfig ||
      previewSession ||
      createPreview.isPending
    ) {
      return;
    }

    createPreview
      .mutateAsync({
        threadId,
        artifactId: manifestId,
        rootPath: manifest.source_path ?? "",
        command: dynamicPreviewConfig.command,
        port: dynamicPreviewConfig.port,
      })
      .catch((error) => {
        toast.error(
          error instanceof Error
            ? error.message
            : "Failed to start live preview session",
        );
      });
  }, [
    createPreview,
    dynamicPreviewConfig,
    manifest,
    manifestId,
    previewSession,
    threadId,
  ]);

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
    if (!previewSession) {
      if (!manifestId || !manifest || !dynamicPreviewConfig) {
        return;
      }
      try {
        await createPreview.mutateAsync({
          threadId,
          artifactId: manifestId,
          rootPath: manifest.source_path ?? "",
          command: dynamicPreviewConfig.command,
          port: dynamicPreviewConfig.port,
        });
        setPreviewReloadKey((value) => value + 1);
      } catch (error) {
        toast.error(
          error instanceof Error
            ? error.message
            : "Failed to start live preview session",
        );
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
      toast.error(
        error instanceof Error
          ? error.message
          : "Failed to restart live preview session",
      );
    }
  }, [
    createPreview,
    dynamicPreviewConfig,
    manifest,
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
      <ArtifactHeader className="px-2">
        <div className="flex items-center gap-2">
          <ArtifactTitle>
            {isWriteFile ? (
              <div className="px-2">{getFileName(filepath)}</div>
            ) : (
              <Select value={filepathFromProps} onValueChange={select}>
                <SelectTrigger className="border-none bg-transparent! shadow-none select-none focus:outline-0 active:outline-0">
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
            <Badge variant="secondary" className="rounded text-[10px]">
              <ActivityIcon className="mr-1 size-3" />
              {previewSession?.status ?? "starting"}
            </Badge>
          )}
        </div>
        <div className="flex min-w-0 grow items-center justify-center">
          {isDynamicManifest && (
            <ToggleGroup
              className="mx-auto"
              type="single"
              variant="outline"
              size="sm"
              value={viewMode}
              onValueChange={(value) => {
                if (value) {
                  setViewMode(value as "preview" | "logs");
                }
              }}
            >
              <ToggleGroupItem value="preview">
                <EyeIcon />
              </ToggleGroupItem>
              <ToggleGroupItem value="logs">
                <ActivityIcon />
              </ToggleGroupItem>
            </ToggleGroup>
          )}
          {!isDynamicManifest && isSupportPreview && (
            <ToggleGroup
              className="mx-auto"
              type="single"
              variant="outline"
              size="sm"
              value={viewMode}
              onValueChange={(value) => {
                if (value) {
                  setViewMode(value as "code" | "preview");
                }
              }}
            >
              <ToggleGroupItem value="code">
                <Code2Icon />
              </ToggleGroupItem>
              <ToggleGroupItem value="preview">
                <EyeIcon />
              </ToggleGroupItem>
            </ToggleGroup>
          )}
        </div>
        <div className="flex items-center gap-2">
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
                  disabled={createPreview.isPending || restartPreview.isPending}
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
        {isDynamicManifest && manifest && (
          <DynamicArtifactPreviewPanel
            key={`${previewSession?.id ?? "preview"}-${previewReloadKey}`}
            manifest={manifest}
            previewUrl={previewUrl}
            previewStatus={previewSession?.status}
            previewError={previewSession?.error}
            logs={previewLogs?.logs ?? ""}
            logsStatus={previewLogs?.status ?? previewSession?.status}
            viewMode={viewMode}
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

function DynamicArtifactPreviewPanel({
  manifest,
  previewUrl,
  previewStatus,
  previewError,
  logs,
  logsStatus,
  viewMode,
}: {
  manifest: ArtifactManifest;
  previewUrl?: string;
  previewStatus?: "starting" | "running" | "failed" | "stopped";
  previewError?: string | null;
  logs: string;
  logsStatus?: "starting" | "running" | "failed" | "stopped";
  viewMode: "code" | "preview" | "logs";
}) {
  if (viewMode === "logs") {
    return (
      <div className="bg-background flex size-full flex-col">
        <div className="border-border/60 flex items-center justify-between border-b px-4 py-2">
          <div className="text-sm font-medium">Preview Logs</div>
          <Badge variant="secondary" className="rounded text-[10px]">
            {logsStatus ?? previewStatus ?? "starting"}
          </Badge>
        </div>
        <pre className="bg-muted/20 text-foreground size-full overflow-auto p-4 font-mono text-xs whitespace-pre-wrap">
          {logs || "Waiting for preview logs..."}
        </pre>
      </div>
    );
  }

  if (!previewUrl) {
    return (
      <div className="flex size-full flex-col items-center justify-center gap-3 px-6 text-center">
        <Badge variant="secondary" className="rounded text-[10px]">
          {previewStatus ?? "starting"}
        </Badge>
        <div className="text-sm font-medium">{manifest.title}</div>
        <div className="text-muted-foreground max-w-md text-sm">
          {previewError ??
            "Starting the live preview session. Switch to Logs to watch the dev server come up."}
        </div>
      </div>
    );
  }

  return (
    <iframe
      key={previewUrl}
      className="size-full"
      src={previewUrl}
      title={manifest.title}
    />
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
