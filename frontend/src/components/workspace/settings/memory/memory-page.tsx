"use client";

import {
  DownloadIcon,
  EllipsisIcon,
  PlusIcon,
  SparklesIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useI18n } from "@/core/i18n/hooks";
import { exportMemory } from "@/core/memory/api";
import { useImportMemory, useMemory } from "@/core/memory/hooks";
import type { UserMemory } from "@/core/memory/types";
import { isImportedMemory } from "@/core/memory/validate";

import { FactsList } from "./facts-list";
import {
  AddFactDialog,
  CleanupMemoryDialog,
  ClearMemoryDialog,
} from "./memory-dialogs";
import { SummaryCard } from "./summary-card";

const MAIN: { key: keyof UserMemory["user"]; title: string }[] = [
  { key: "workContext", title: "Work" },
  { key: "personalContext", title: "Personal" },
  { key: "topOfMind", title: "Top of mind" },
];
const HISTORY: { key: keyof UserMemory["history"]; title: string }[] = [
  { key: "recentMonths", title: "Recent months" },
  { key: "earlierContext", title: "Earlier" },
  { key: "longTermBackground", title: "Background" },
];

function isEmpty(memory: UserMemory) {
  return (
    MAIN.every((s) => !memory.user[s.key].summary.trim()) &&
    HISTORY.every((s) => !memory.history[s.key].summary.trim()) &&
    memory.facts.length === 0
  );
}

/**
 * Settings → Memory, redesigned (Phase 2.6).
 *
 * One primary action, Add fact; Import, Export, Clean up and Clear all are in
 * the ⋯ menu. The toolbar wraps rather than overlapping at any width.
 */
export function MemoryPage() {
  const { t } = useI18n();
  const { memory, isLoading, error } = useMemory();
  const importMemory = useImportMemory();
  const router = useRouter();
  // The tab is in the URL (?tab=facts), so a link can open either.
  const tab = useSearchParams().get("tab") === "facts" ? "facts" : "summary";
  const setTab = (value: string) =>
    router.replace(
      value === "facts"
        ? "/workspace/settings/memory?tab=facts"
        : "/workspace/settings/memory",
    );
  const [adding, setAdding] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function handleExport() {
    try {
      const data = await exportMemory();
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `omniharness-memory-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Export failed");
    }
  }

  async function handleImport(file: File) {
    try {
      const parsed: unknown = JSON.parse(await file.text());
      if (!isImportedMemory(parsed)) {
        toast.error("That file is not a complete memory export.");
        return;
      }
      importMemory.mutate(parsed, {
        onSuccess: () => toast.success(`Imported ${file.name}`),
        onError: (err) => toast.error(err.message),
      });
    } catch {
      toast.error("That file is not valid JSON.");
    }
  }

  const history = memory
    ? HISTORY.filter((s) => memory.history[s.key].summary.trim())
    : [];

  return (
    <div className="space-y-5" data-testid="memory-page">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">{t.settings.memory.title}</h1>
        <p className="text-muted-foreground text-sm">
          {t.settings.memory.description}
        </p>
      </header>

      <Tabs value={tab} onValueChange={setTab} className="gap-4">
        {/* The toolbar: tabs on the left, actions on the right, wrapping as a
            whole when the width runs out, never overlapping. */}
        <div
          className="flex flex-wrap items-center justify-between gap-3"
          data-testid="memory-toolbar"
        >
          <TabsList>
            <TabsTrigger value="summary">Summary</TabsTrigger>
            <TabsTrigger value="facts">
              Facts
              {memory && memory.facts.length > 0 && (
                <span className="text-muted-foreground ml-1 tabular-nums">
                  {memory.facts.length}
                </span>
              )}
            </TabsTrigger>
          </TabsList>
          <div className="flex items-center gap-2">
            <Button onClick={() => setAdding(true)} disabled={!memory}>
              <PlusIcon />
              Add fact
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="icon"
                  aria-label="More memory actions"
                >
                  <EllipsisIcon />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-52">
                <DropdownMenuItem onSelect={() => fileInput.current?.click()}>
                  <UploadIcon />
                  Import…
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => void handleExport()}>
                  <DownloadIcon />
                  Export
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => setCleaning(true)}
                  disabled={!memory || isEmpty(memory)}
                >
                  <SparklesIcon />
                  Clean up memory…
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  variant="destructive"
                  onSelect={() => setClearing(true)}
                  disabled={!memory || isEmpty(memory)}
                >
                  <Trash2Icon />
                  Clear all memory…
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <input
              ref={fileInput}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleImport(file);
                e.target.value = "";
              }}
            />
          </div>
        </div>

        {error != null && (
          <Alert variant="destructive">
            <AlertTitle>I cannot read your memory</AlertTitle>
            <AlertDescription>{String(error)}</AlertDescription>
          </Alert>
        )}

        {isLoading && (
          <div className="grid gap-3" data-testid="memory-loading">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-28 rounded-xl" />
            ))}
          </div>
        )}

        {memory && isEmpty(memory) && (
          <div
            className="text-muted-foreground rounded-xl border border-dashed p-8 text-center text-sm"
            data-testid="memory-empty"
          >
            Nothing remembered yet. As we talk I&apos;ll keep durable things
            here — what you work on, your preferences, the people you mention —
            and you can correct any of it.
          </div>
        )}

        {memory && !isEmpty(memory) && (
          <>
            <TabsContent value="summary" className="space-y-3">
              {MAIN.map((s) => (
                <SummaryCard
                  key={s.key}
                  title={s.title}
                  group="user"
                  sectionKey={s.key}
                  summary={memory.user[s.key].summary}
                  updatedAt={memory.user[s.key].updatedAt}
                />
              ))}
              {history.length > 0 && (
                <>
                  <h2 className="text-muted-foreground pt-2 text-xs font-medium tracking-wide uppercase">
                    History
                  </h2>
                  {history.map((s) => (
                    <SummaryCard
                      key={s.key}
                      title={s.title}
                      group="history"
                      sectionKey={s.key}
                      summary={memory.history[s.key].summary}
                      updatedAt={memory.history[s.key].updatedAt}
                    />
                  ))}
                </>
              )}
            </TabsContent>
            <TabsContent value="facts">
              <FactsList facts={memory.facts} />
            </TabsContent>
          </>
        )}
      </Tabs>

      <AddFactDialog open={adding} onOpenChange={setAdding} />
      <ClearMemoryDialog open={clearing} onOpenChange={setClearing} />
      <CleanupMemoryDialog open={cleaning} onOpenChange={setCleaning} />
    </div>
  );
}
