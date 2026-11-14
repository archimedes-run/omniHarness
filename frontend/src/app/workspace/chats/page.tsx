"use client";

import { ArchiveRestoreIcon, SearchIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  PageColumn,
  PageHeader,
  RowList,
} from "@/components/workspace/page-kit";
import { useI18n } from "@/core/i18n/hooks";
import { folderOf, foldersOf, unarchivePatch } from "@/core/threads/organise";
import { useOrganiseThread, useThreads } from "@/core/threads/queries";
import { pathOfThread, titleOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

const ARCHIVED_QUERY = {
  limit: 200,
  sortBy: "updated_at",
  sortOrder: "desc",
  select: ["thread_id", "updated_at", "values", "metadata"],
  archived: true,
} as const;

/**
 * Chats (Feature 006): every conversation, searchable, as the boards' divided
 * rows. The top bar names the page, so there is no breadcrumb header here.
 *
 * Active chats by default; Archived lists archived chats by folder (e.g.
 * "Tests"), each with Unarchive. Nothing is deleted by archiving.
 */
export default function ChatsPage() {
  const { t } = useI18n();
  const [view, setView] = useState<"active" | "archived">("active");
  const [folder, setFolder] = useState<string | null>(null);
  const active = useThreads();
  const archived = useThreads({
    ...ARCHIVED_QUERY,
    select: [...ARCHIVED_QUERY.select],
  });
  const {
    data: threads,
    isLoading,
    error,
  } = view === "active" ? active : archived;
  const folders = useMemo(
    () => foldersOf(archived.data ?? []),
    [archived.data],
  );
  const organise = useOrganiseThread();
  const [search, setSearch] = useState("");

  useEffect(() => {
    document.title = `${t.pages.chats} - ${t.pages.appName}`;
  }, [t.pages.chats, t.pages.appName]);

  const filteredThreads = useMemo(() => {
    return threads?.filter((thread) => {
      if (
        view === "archived" &&
        folder !== null &&
        folderOf(thread) !== folder
      ) {
        return false;
      }
      return titleOfThread(thread).toLowerCase().includes(search.toLowerCase());
    });
  }, [threads, search, view, folder]);

  const chip = (selected: boolean) =>
    cn(
      "rounded-full border px-3 py-1 text-sm max-md:min-h-11",
      selected
        ? "border-primary bg-primary-subtle text-foreground font-medium"
        : "border-border text-muted-foreground hover:text-foreground",
    );

  return (
    <PageColumn width="narrow">
      <PageHeader title={t.sidebar.chats} />
      <label className="bg-card border-border-strong flex items-center gap-2 rounded-lg border px-3 py-2">
        <SearchIcon className="text-muted-foreground size-4" aria-hidden />
        <span className="sr-only">{t.chats.searchChats}</span>
        <input
          type="search"
          className="placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent outline-none"
          placeholder={t.chats.searchChats}
          autoFocus
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </label>
      <div
        className="flex flex-wrap items-center gap-2"
        role="group"
        aria-label="Show"
      >
        <button
          type="button"
          className={chip(view === "active")}
          aria-pressed={view === "active"}
          onClick={() => setView("active")}
          data-testid="chats-view-active"
        >
          {t.chats.active}
        </button>
        <button
          type="button"
          className={chip(view === "archived" && folder === null)}
          aria-pressed={view === "archived" && folder === null}
          onClick={() => {
            setView("archived");
            setFolder(null);
          }}
          data-testid="chats-view-archived"
        >
          {t.chats.archived}
        </button>
        {view === "archived" &&
          folders.map((f) => (
            <button
              key={f}
              type="button"
              className={chip(folder === f)}
              aria-pressed={folder === f}
              onClick={() => setFolder(f)}
              data-testid="chats-folder"
            >
              {f}
            </button>
          ))}
      </div>
      {isLoading && <p className="text-muted-foreground">Loading…</p>}
      {error != null && (
        <p className="text-destructive" role="alert">
          I can&apos;t list your chats: {String(error)}
        </p>
      )}
      {threads?.length === 0 && (
        <p className="text-muted-foreground" data-testid="chats-empty">
          {view === "archived" ? t.chats.noArchived : "No chats yet."}
        </p>
      )}
      {filteredThreads && filteredThreads.length > 0 && (
        <RowList data-testid="chats-list">
          {filteredThreads.map((thread) => (
            <li key={thread.thread_id} className="flex items-center">
              <Link
                href={pathOfThread(thread)}
                className="hover:bg-accent flex min-w-0 flex-1 items-center gap-3 px-[18px] py-3"
              >
                <span className="min-w-0 flex-1 truncate font-medium">
                  {titleOfThread(thread)}
                </span>
                {view === "archived" && folderOf(thread) && (
                  <span className="text-muted-foreground shrink-0 text-xs">
                    {folderOf(thread)}
                  </span>
                )}
                {thread.updated_at && (
                  <span className="text-muted-foreground shrink-0 text-xs">
                    {formatTimeAgo(thread.updated_at)}
                  </span>
                )}
              </Link>
              {view === "archived" && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="mr-2 shrink-0 max-md:min-h-11"
                  disabled={organise.isPending}
                  onClick={() =>
                    organise.mutate({
                      threadId: thread.thread_id,
                      patch: unarchivePatch(),
                    })
                  }
                  data-testid="chat-unarchive"
                >
                  <ArchiveRestoreIcon />
                  {t.chats.unarchive}
                </Button>
              )}
            </li>
          ))}
        </RowList>
      )}
      {threads && threads.length > 0 && filteredThreads?.length === 0 && (
        <p className="text-muted-foreground">No chat matches that search.</p>
      )}
    </PageColumn>
  );
}
