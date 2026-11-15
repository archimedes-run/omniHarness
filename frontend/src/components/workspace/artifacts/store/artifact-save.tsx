"use client";

import {
  BookmarkIcon,
  CheckIcon,
  ChevronDownIcon,
  DownloadIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { downloadUrl, type ArtifactSummary } from "@/core/artifacts/store-api";
import { useSaveArtifact } from "@/core/artifacts/store-hooks";
import { downloadForms, refusalWords } from "@/core/artifacts/store-logic";

/**
 * Spec 012 (owner's correction): nothing lands in the store by itself. Each
 * artifact offers **Save** (then "Saved ✓", with Unsave in its menu) and
 * **Download** (one form, or a small menu of forms) through the gateway's
 * download route (api.md GET …/download). Owner clicks only. An archived
 * artifact may be saved too.
 */
export function SaveDownload({
  artifact,
  version,
  size = "sm",
  download = true,
}: {
  artifact: Pick<
    ArtifactSummary,
    "id" | "kind" | "saved" | "code" | "latest_version"
  >;
  version: number;
  size?: "sm" | "xs";
  /** False where the view has its own downloads (the code-kind viewer). */
  download?: boolean;
}) {
  const save = useSaveArtifact(artifact.id);
  // Optimistic: the pressed state shows at once; a refusal rolls it back.
  const saved = save.isPending
    ? save.variables
    : save.isSuccess
      ? save.data.saved
      : artifact.saved;
  // A code version that did not build has no page to download. The summary
  // speaks for the latest version only; for an older one the gateway's 409
  // build_failed still answers.
  const built = !(
    artifact.code?.build_state === "build_failed" &&
    version === artifact.latest_version
  );
  const forms = download ? downloadForms(artifact.kind, built) : [];
  const cls =
    size === "xs" ? "h-7 px-2 text-xs max-md:min-h-11" : "max-md:min-h-11";
  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      data-testid="artifact-save-download"
    >
      {saved ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className={cls}
              data-testid="artifact-store-saved"
              aria-label="Saved. More options"
            >
              <CheckIcon />
              Saved
              <ChevronDownIcon className="size-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem
              onSelect={() => save.mutate(false)}
              data-testid="artifact-store-unsave"
            >
              Unsave
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className={cls}
          disabled={save.isPending}
          onClick={() => save.mutate(true)}
          data-testid="artifact-store-save"
        >
          <BookmarkIcon />
          Save
        </Button>
      )}
      {forms.length === 0 ? null : forms.length === 1 ? (
        <Button asChild size="sm" variant="ghost" className={cls}>
          <a
            href={downloadUrl(artifact.id, version, forms[0]!.form)}
            download
            data-testid="artifact-store-download"
          >
            <DownloadIcon />
            Download
          </a>
        </Button>
      ) : (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className={cls}
              data-testid="artifact-store-download-menu"
            >
              <DownloadIcon />
              Download
              <ChevronDownIcon className="size-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {forms.map((f) => (
              <DropdownMenuItem key={f.label} asChild>
                <a
                  href={downloadUrl(artifact.id, version, f.form)}
                  download
                  data-testid="artifact-store-download-form"
                  data-form={f.form}
                >
                  {f.label}
                </a>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      {save.isError && (
        <span role="alert" className="text-destructive text-xs">
          {refusalWords(save.error)}
        </span>
      )}
    </div>
  );
}
