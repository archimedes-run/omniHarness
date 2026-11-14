"use client";

import { ArchiveIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { folderOf, isArchived, unarchivePatch } from "@/core/threads/organise";
import { useOrganiseThread, useThreadRecord } from "@/core/threads/queries";

/**
 * An archived chat still opens by its link; this says so, with Unarchive.
 * Nothing shows for a chat that is not archived or cannot be read.
 */
export function ArchivedBanner({ threadId }: { threadId: string }) {
  const { t } = useI18n();
  const { data } = useThreadRecord(threadId);
  const organise = useOrganiseThread();
  if (!data || !isArchived(data)) return null;
  const folder = folderOf(data);
  return (
    <div
      className="border-border bg-muted text-foreground flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b px-4 py-1.5 text-sm"
      data-testid="archived-banner"
      role="status"
    >
      <span className="inline-flex items-center gap-1.5">
        <ArchiveIcon className="size-4" aria-hidden />
        {t.chats.archivedBanner}
        {folder ? ` · ${folder}` : ""}
      </span>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-7 max-md:min-h-11"
        disabled={organise.isPending}
        onClick={() => organise.mutate({ threadId, patch: unarchivePatch() })}
        data-testid="archived-banner-unarchive"
      >
        {t.chats.unarchive}
      </Button>
    </div>
  );
}
