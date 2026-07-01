"use client";

import { Loader2Icon, LockIcon, SearchIcon, XIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { ToolIcon } from "@/components/workspace/tools/tool-icon";
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

export function ToolsPicker({
  threadId,
  open,
  onOpenChange,
  placement = "top",
}: {
  threadId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** "bottom" opens beneath the composer (new chat), "top" opens above it. */
  placement?: "top" | "bottom";
}) {
  const panelRef = useRef<HTMLDivElement | null>(null);
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

  // Close on outside click + Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onOpenChange(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onOpenChange]);

  const overCap = count != null && count.count > count.cap;

  const persist = useCallback(
    async (next: Set<string>) => {
      setSelected(new Set(next));
      try {
        const saved = await putThreadSelection(threadId, Array.from(next));
        setSelected(new Set(saved.sources));
        void refreshCount();
      } catch {
        void load();
      }
    },
    [threadId, refreshCount, load],
  );

  const toggle = useCallback(
    (item: ToolCatalogItem, on: boolean) => {
      if (pinned.has(item.tool_id)) return;
      const next = new Set(selected);
      if (on) {
        if (overCap) return;
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
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          const status = await getComposioConnectionStatus(item.toolkit);
          if (status.status === "active" || status.status === "connected") {
            await load();
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

  if (!open) return null;

  const tabs = ["All", ...categories];

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label="Tools for this chat"
      className={cn(
        // Full chat-window width (anchored to the composer's relative root).
        "absolute inset-x-0 z-40",
        "flex max-h-[62vh] flex-col overflow-hidden rounded-2xl",
        // Solid surface matching the rest of the app (composer/dialog/card).
        "bg-background border-border border shadow-xl",
        placement === "bottom"
          ? "animate-in fade-in slide-in-from-top-2 top-full mt-3 origin-top"
          : "animate-in fade-in slide-in-from-bottom-2 bottom-full mb-3 origin-bottom",
      )}
    >
      {/* Header */}
      <div className="border-border border-b px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-semibold">Tools for this chat</span>
          <div className="flex items-center gap-2">
            {count && (
              <Badge
                variant={overCap ? "destructive" : "secondary"}
                className="tabular-nums"
              >
                {count.count} / {count.cap}
              </Badge>
            )}
            <button
              onClick={() => onOpenChange(false)}
              className="text-muted-foreground hover:bg-muted rounded-full p-1 transition-colors"
              aria-label="Close"
            >
              <XIcon className="size-4" />
            </button>
          </div>
        </div>
        <div className="relative mt-3">
          <SearchIcon className="text-muted-foreground absolute top-1/2 left-3 size-3.5 -translate-y-1/2" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search tools…"
            className="border-border bg-muted/50 placeholder:text-muted-foreground focus:ring-ring w-full rounded-xl border py-2 pr-3 pl-9 text-sm outline-none focus:ring-2"
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
                  ? "border-neutral-900 bg-neutral-900 text-white"
                  : "text-muted-foreground border-border hover:bg-muted",
              )}
            >
              {c}
            </button>
          ))}
        </div>
        {overCap && (
          <p className="text-destructive mt-2 text-xs">
            You&apos;ve reached this model&apos;s {count?.cap}-tool limit. Turn
            some off to enable others.
          </p>
        )}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        <div className="divide-border divide-y">
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
                  className="hover:bg-muted/60 flex items-center gap-3 px-5 py-3 transition-colors"
                >
                  <ToolIcon
                    source={item.source}
                    name={item.name}
                    slug={item.toolkit}
                    origin={item.origin}
                    description={item.description}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium">
                        {item.name}
                      </span>
                      <Badge
                        variant="outline"
                        className="text-muted-foreground border-border shrink-0 text-[10px]"
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
                      className="bg-neutral-900 text-white hover:bg-neutral-800"
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
      </div>
    </div>
  );
}
