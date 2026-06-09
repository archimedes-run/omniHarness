import {
  DownloadIcon,
  Globe2Icon,
  LoaderIcon,
  PackageIcon,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useArtifactManifests } from "@/core/artifacts/hooks";
import {
  artifactDisplayName,
  normalizeArtifactEntries,
  parseArtifactManifestValue,
  urlOfArtifact,
} from "@/core/artifacts/utils";
import { useI18n } from "@/core/i18n/hooks";
import { installSkill } from "@/core/skills/api";
import {
  getFileExtensionDisplayName,
  getFileIcon,
  getFileName,
} from "@/core/utils/files";
import { cn } from "@/lib/utils";

import { useArtifacts } from "./context";

export function ArtifactFileList({
  className,
  files,
  threadId,
}: {
  className?: string;
  files: string[];
  threadId: string;
}) {
  const { t } = useI18n();
  const { select: selectArtifact, setOpen } = useArtifacts();
  const { manifests } = useArtifactManifests({ threadId });
  const [installingFile, setInstallingFile] = useState<string | null>(null);
  const normalizedFiles = useMemo(() => {
    return normalizeArtifactEntries(files);
  }, [files]);
  const manifestsById = useMemo(() => {
    return new Map(manifests.map((manifest) => [manifest.id, manifest]));
  }, [manifests]);

  const handleClick = useCallback(
    (filepath: string) => {
      selectArtifact(filepath);
      setOpen(true);
    },
    [selectArtifact, setOpen],
  );

  const handleInstallSkill = useCallback(
    async (e: React.MouseEvent, filepath: string) => {
      e.stopPropagation();
      e.preventDefault();

      if (installingFile) return;

      setInstallingFile(filepath);
      try {
        const result = await installSkill({
          thread_id: threadId,
          path: filepath,
        });
        if (result.success) {
          toast.success(result.message);
        } else {
          toast.error(result.message || "Failed to install skill");
        }
      } catch (error) {
        console.error("Failed to install skill:", error);
        toast.error("Failed to install skill");
      } finally {
        setInstallingFile(null);
      }
    },
    [threadId, installingFile],
  );

  return (
    <ul className={cn("flex w-full flex-col gap-4", className)}>
      {normalizedFiles.map((file) => {
        const manifestId = parseArtifactManifestValue(file);
        const manifest = manifestId ? manifestsById.get(manifestId) : null;
        const downloadPath =
          manifest?.entrypoint_path ?? manifest?.manifest_path ?? file;
        const manifestBadge =
          manifest?.preview.mode === "dev_server" ? "Live App" : "Static Site";
        return (
          <Card
            key={file}
            className="relative cursor-pointer p-3"
            onClick={() => handleClick(file)}
          >
            <CardHeader className="grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 pr-2 pl-1">
              <CardTitle className="relative min-w-0 pl-8 leading-tight [overflow-wrap:anywhere] break-words">
                <div className="min-w-0">
                  {artifactDisplayName(file, manifests, getFileName)}
                </div>
                <div className="absolute top-2 -left-0.5">
                  {manifest ? (
                    <Globe2Icon className="text-muted-foreground size-6" />
                  ) : (
                    getFileIcon(file, "size-6")
                  )}
                </div>
              </CardTitle>
              <CardDescription className="flex min-w-0 items-center gap-2 pl-8 text-xs">
                {manifest ? (
                  <Badge variant="secondary" className="rounded text-[10px]">
                    {manifestBadge}
                  </Badge>
                ) : (
                  `${getFileExtensionDisplayName(file)} file`
                )}
              </CardDescription>
              <CardAction className="row-span-1 self-center">
                {!manifest && file.endsWith(".skill") && (
                  <Button
                    variant="ghost"
                    disabled={installingFile === file}
                    onClick={(e) => handleInstallSkill(e, file)}
                  >
                    {installingFile === file ? (
                      <LoaderIcon className="size-4 animate-spin" />
                    ) : (
                      <PackageIcon className="size-4" />
                    )}
                    {t.common.install}
                  </Button>
                )}
                <Button variant="ghost" asChild>
                  <a
                    href={urlOfArtifact({
                      filepath: downloadPath,
                      threadId: threadId,
                      download: true,
                    })}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <DownloadIcon className="size-4" />
                    {t.common.download}
                  </a>
                </Button>
              </CardAction>
            </CardHeader>
          </Card>
        );
      })}
    </ul>
  );
}
