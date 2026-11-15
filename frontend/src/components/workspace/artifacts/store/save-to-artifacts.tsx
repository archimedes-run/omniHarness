"use client";

import { BookmarkIcon, CheckIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useImportChatFile } from "@/core/artifacts/store-hooks";
import { refusalWords } from "@/core/artifacts/store-logic";

/**
 * Spec 012 (owner's correction): a file a chat produced, or a coding job's
 * published site, is saved to the store only when the owner presses
 * "Save to artifacts" (POST /api/artifacts/import): a file becomes one
 * saved artifact, a directory with an index.html one saved web app.
 */
export function SaveToArtifacts({
  threadId,
  path,
  className,
  compact = false,
}: {
  threadId: string;
  path: string;
  className?: string;
  /** An icon button (named for assistive technology): rows in a narrow
   * list, such as the side panel's files, keep room for the file name. */
  compact?: boolean;
}) {
  const save = useImportChatFile(threadId);
  if (save.isSuccess) {
    return (
      <Link
        href={`/workspace/artifacts/${encodeURIComponent(save.data.artifact.id)}`}
        className="text-primary inline-flex items-center gap-1 text-xs underline max-md:min-h-11"
        onClick={(e) => e.stopPropagation()}
        data-testid="save-to-artifacts-done"
      >
        <CheckIcon className="size-3.5" aria-hidden />
        {compact ? (
          <span className="sr-only">Saved. Open in Artifacts</span>
        ) : (
          "Saved. Open in Artifacts"
        )}
      </Link>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Button
        type="button"
        size={compact ? "icon-sm" : "sm"}
        variant="ghost"
        className={className}
        aria-label={compact ? "Save to artifacts" : undefined}
        title={compact ? "Save to artifacts" : undefined}
        disabled={save.isPending}
        onClick={(e) => {
          e.stopPropagation();
          e.preventDefault();
          save.mutate(path);
        }}
        data-testid="save-to-artifacts"
      >
        <BookmarkIcon className="size-4" />
        {!compact && "Save to artifacts"}
      </Button>
      {save.isError && (
        <span role="alert" className="text-destructive text-xs">
          {refusalWords(save.error)}
        </span>
      )}
    </span>
  );
}
