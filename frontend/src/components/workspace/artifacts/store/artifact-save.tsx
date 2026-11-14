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
import {
  useSaveArtifact,
  useSaveUnavailable,
} from "@/core/artifacts/store-hooks";
import { downloadForms, refusalWords } from "@/core/artifacts/store-logic";

/**
 * Spec 012 (owner's correction): nothing lands in the store by itself. Each
 * artifact offers **Save** (then "Saved ✓", with Unsave in its menu) and
 * **Download** (one form, or a small menu of forms). Owner clicks only.
 * Hidden when the gateway has no save routes (no `saved` field, or a save
 * route answered 404).
 */
export function SaveDownload({
  artifact,
  version,
  size = "sm",
}: {
  artifact: Pick<ArtifactSummary, "id" | "kind" | "saved" | "archived">;
  version: number;
  size?: "sm" | "xs";
}) {
  const unavailable = useSaveUnavailable();
  const save = useSaveArtifact(artifact.id);
  if (unavailable || typeof artifact.saved !== "boolean") return null;
  // Optimistic: the pressed state shows at once; a refusal rolls it back.
  const saved = save.isPending
    ? save.variables
    : save.isSuccess
      ? (save.data.saved ?? save.variables)
      : artifact.saved;
  const forms = downloadForms(artifact.kind);
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
              data-testid="artifact-saved"
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
              data-testid="artifact-unsave"
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
          disabled={save.isPending || artifact.archived}
          onClick={() => save.mutate(true)}
          data-testid="artifact-save"
        >
          <BookmarkIcon />
          Save
        </Button>
      )}
      {forms.length === 1 ? (
        <Button asChild size="sm" variant="ghost" className={cls}>
          <a
            href={downloadUrl(artifact.id, version, forms[0]!.form)}
            download
            data-testid="artifact-download"
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
              data-testid="artifact-download-menu"
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
                  data-testid="artifact-download-form"
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
