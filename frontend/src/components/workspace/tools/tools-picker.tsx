"use client";

import { Loader2Icon, LockIcon, SearchIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import {
  getComposioConnectionStatus,
  initiateComposioConnection,
} from "@/core/mcp/api";
import {
  getThreadSelection,
  getThreadToolCount,
  getToolsCatalog,
  putThreadSelection,
  type ToolCatalogItem,
} from "@/core/tools/api";
import { cn } from "@/lib/utils";

// Branding-neutral brand marks keyed by the catalog icon slug (no vendor name).
const ICONS: Record<string, string> = {
  gmail: "📧",
  googlecalendar: "📅",
  googledrive: "🗂️",
  slack: "💬",
  notion: "📝",
  github: "🐙",
  linear: "⚡",
  outlook: "📮",
};

function itemIcon(item: ToolCatalogItem): string {
  const mark = item.icon ? ICONS[item.icon] : undefined;
  if (mark) return mark;
  return item.source === "local" ? "🧩" : "🔌";
}

export function ToolsPicker({
  threadId,
  open,
  onOpenChange,
}: {
  threadId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [items, setItems] = useState<ToolCatalogItem[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pinned, setPinned] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>("All");
  const [count, setCount] = useState<{ count: number; cap: number } | null>(
    null,
  );
  const [connecting, setConnecting] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refreshCount = useCallback(async () => {
    try {
      const c = await getThreadToolCount(threadId);
      setCount({ count: c.count, cap: c.cap });
    } catch {
      /* count is best-effort */
    }
  }, [threadId]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [catalog, selection] = await Promise.all([
        getToolsCatalog(),
        getThreadSelection(threadId),
      ]);
      setItems(catalog.items);
      setCategories(catalog.categories);
      setSelected(new Set(selection.sources));
      setPinned(new Set(selection.pinned));
      void refreshCount();
    } finally {
      setLoading(false);
    }
  }, [threadId, refreshCount]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const overCap = count != null && count.count > count.cap;

  const persist = useCallback(
    async (next: Set<string>) => {
      setSelected(new Set(next));
      try {
        const saved = await putThreadSelection(threadId, Array.from(next));
        setSelected(new Set(saved.sources));
        void refreshCount();
      } catch {
        void load(); // reload authoritative state on failure
      }
    },
    [threadId, refreshCount, load],
  );

  const toggle = useCallback(
    (item: ToolCatalogItem, on: boolean) => {
      if (pinned.has(item.tool_id)) return; // pinned are non-removable
      const next = new Set(selected);
      if (on) {
        if (overCap) return; // block enabling past the cap
        next.add(item.tool_id);
      } else {
        next.delete(item.tool_id);
      }
      void persist(next);
    },
    [selected, pinned, overCap, persist],
  );

  const connect = useCallback(
    async (item: ToolCatalogItem) => {
      if (!item.toolkit) return;
      setConnecting(item.tool_id);
      try {
        const redirect = `${window.location.origin}/composio/callback`;
        const res = await initiateComposioConnection(item.toolkit, redirect);
        if ("composio_redirect_url" in res && res.composio_redirect_url) {
          window.open(
            res.composio_redirect_url,
            "_blank",
            "width=520,height=680",
          );
        }
        // Poll our own API until the toolkit reports connected.
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          const status = await getComposioConnectionStatus(item.toolkit);
          if (status.status === "active" || status.status === "connected") {
            await load(); // refresh connected flags; tool becomes enable-able
            break;
          }
        }
      } finally {
        setConnecting(null);
      }
    },
    [load],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((it) => {
      if (activeCategory !== "All" && it.category !== activeCategory)
        return false;
      if (!q) return true;
      return (
        it.name.toLowerCase().includes(q) ||
        it.description.toLowerCase().includes(q)
      );
    });
  }, [items, query, activeCategory]);

  const tabs = ["All", ...categories];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[80vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-5 py-4">
          <div className="flex items-center justify-between gap-3">
            <DialogTitle className="text-base">Tools for this chat</DialogTitle>
            {count && (
              <Badge
                variant={overCap ? "destructive" : "secondary"}
                className="tabular-nums"
              >
                {count.count} / {count.cap}
              </Badge>
            )}
          </div>
          <div className="relative mt-3">
            <SearchIcon className="text-muted-foreground absolute top-1/2 left-3 size-3.5 -translate-y-1/2" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search tools…"
              className="pl-9"
            />
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {tabs.map((c) => (
              <button
                key={c}
                onClick={() => setActiveCategory(c)}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-xs transition-colors",
                  activeCategory === c
                    ? "bg-primary text-primary-foreground border-primary"
                    : "hover:bg-muted text-muted-foreground",
                )}
              >
                {c}
              </button>
            ))}
          </div>
          {overCap && (
            <p className="text-destructive mt-2 text-xs">
              You&apos;ve reached this model&apos;s {count?.cap}-tool limit.
              Turn some off to enable others.
            </p>
          )}
        </DialogHeader>

        <ScrollArea className="flex-1">
          <div className="divide-y">
            {loading && (
              <div className="text-muted-foreground flex items-center justify-center gap-2 py-10 text-sm">
                <Loader2Icon className="size-4 animate-spin" /> Loading…
              </div>
            )}
            {!loading &&
              filtered.map((item) => {
                const isPinned = pinned.has(item.tool_id);
                const isOn = selected.has(item.tool_id) || isPinned;
                const needsConnect =
                  item.source === "connector" && !item.connected;
                return (
                  <div
                    key={item.tool_id}
                    className="flex items-center gap-3 px-5 py-3"
                  >
                    <span className="text-lg">{itemIcon(item)}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">
                          {item.name}
                        </span>
                        <Badge
                          variant="outline"
                          className="text-muted-foreground shrink-0 text-[10px]"
                        >
                          {item.category}
                        </Badge>
                        {isPinned && (
                          <LockIcon className="text-muted-foreground size-3" />
                        )}
                      </div>
                      {item.description && (
                        <p className="text-muted-foreground truncate text-xs">
                          {item.description}
                        </p>
                      )}
                    </div>
                    {needsConnect ? (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={connecting === item.tool_id}
                        onClick={() => void connect(item)}
                      >
                        {connecting === item.tool_id ? (
                          <Loader2Icon className="size-3.5 animate-spin" />
                        ) : (
                          "Connect"
                        )}
                      </Button>
                    ) : (
                      <Switch
                        checked={isOn}
                        disabled={isPinned || (!isOn && overCap)}
                        onCheckedChange={(on) => toggle(item, on)}
                      />
                    )}
                  </div>
                );
              })}
            {!loading && filtered.length === 0 && (
              <div className="text-muted-foreground py-10 text-center text-sm">
                No tools match &ldquo;{query}&rdquo;.
              </div>
            )}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
