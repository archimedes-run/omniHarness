"use client";

import { SearchIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  PageColumn,
  PageHeader,
  RowList,
} from "@/components/workspace/page-kit";
import { useI18n } from "@/core/i18n/hooks";
import { useThreads } from "@/core/threads/queries";
import { pathOfThread, titleOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";

/**
 * Chats (Feature 006): every conversation, searchable, as the boards' divided
 * rows. The top bar names the page, so there is no breadcrumb header here.
 */
export default function ChatsPage() {
  const { t } = useI18n();
  const { data: threads, isLoading, error } = useThreads();
  const [search, setSearch] = useState("");

  useEffect(() => {
    document.title = `${t.pages.chats} - ${t.pages.appName}`;
  }, [t.pages.chats, t.pages.appName]);

  const filteredThreads = useMemo(() => {
    return threads?.filter((thread) => {
      return titleOfThread(thread).toLowerCase().includes(search.toLowerCase());
    });
  }, [threads, search]);

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
      {isLoading && <p className="text-muted-foreground">Loading…</p>}
      {error != null && (
        <p className="text-destructive" role="alert">
          I can&apos;t list your chats: {String(error)}
        </p>
      )}
      {threads?.length === 0 && (
        <p className="text-muted-foreground" data-testid="chats-empty">
          No chats yet.
        </p>
      )}
      {filteredThreads && filteredThreads.length > 0 && (
        <RowList data-testid="chats-list">
          {filteredThreads.map((thread) => (
            <li key={thread.thread_id}>
              <Link
                href={pathOfThread(thread)}
                className="hover:bg-accent flex items-center gap-3 px-[18px] py-3"
              >
                <span className="min-w-0 flex-1 truncate font-medium">
                  {titleOfThread(thread)}
                </span>
                {thread.updated_at && (
                  <span className="text-muted-foreground shrink-0 text-xs">
                    {formatTimeAgo(thread.updated_at)}
                  </span>
                )}
              </Link>
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
