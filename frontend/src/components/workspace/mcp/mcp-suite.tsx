"use client";

import {
  CheckCircle2Icon,
  Loader2Icon,
  PlugIcon,
  RotateCwIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { IntegrationIcon } from "@/components/workspace/tools/integration-icon";
import { disconnectComposioToolkit, getComposioCatalog } from "@/core/mcp/api";
import { connectComposioToolkit } from "@/core/mcp/connect";
import { type ComposioToolkit } from "@/core/mcp/types";
import { cn } from "@/lib/utils";

/**
 * The app catalog (Composio 1-click connect), opened from MCP Suite >
 * Connected's "Browse apps". Feature 006: the rest of the old suite (My MCPs)
 * is the Build tab now.
 */

// ── 1-Click Connections tab ───────────────────────────────────────────────────

const CONNECTION_CATEGORIES = [
  "All",
  "Productivity",
  "Communication",
  "Knowledge",
  "Dev Tools",
  "Project Mgmt",
];

export function AppCatalog() {
  const [toolkits, setToolkits] = useState<ComposioToolkit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState("All");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState<string | null>(
    null,
  );

  const refreshCatalog = useCallback(async () => {
    try {
      const data = await getComposioCatalog();
      setToolkits(data);
      setError(null);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Failed to load connectors",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshCatalog();
  }, [refreshCatalog]);

  const handleConnect = useCallback(
    async (toolkit: string) => {
      setBusy(toolkit);
      try {
        // Mark as pending locally for immediate feedback while OAuth runs;
        // the button is busy only until the popup opens, as before.
        const outcome = connectComposioToolkit(toolkit, () => {
          setBusy(null);
          setToolkits((prev) =>
            prev.map((t) =>
              t.slug === toolkit ? { ...t, status: "pending" } : t,
            ),
          );
        });
        await outcome;
        await refreshCatalog();
      } catch (err: unknown) {
        setError(
          err instanceof Error ? err.message : "Failed to start connection",
        );
        await refreshCatalog();
      } finally {
        setBusy(null);
      }
    },
    [refreshCatalog],
  );

  const handleDisconnect = useCallback(
    async (toolkit: string) => {
      setBusy(toolkit);
      setConfirmDisconnect(null);
      try {
        await disconnectComposioToolkit(toolkit);
        await refreshCatalog();
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Failed to disconnect");
      } finally {
        setBusy(null);
      }
    },
    [refreshCatalog],
  );

  const filtered = toolkits.filter(
    (t) => activeCategory === "All" || t.category === activeCategory,
  );

  return (
    <div className="flex flex-col gap-5">
      <p className="text-muted-foreground text-sm">
        Connect your accounts with one click. OmniHarness uses Composio to
        handle OAuth securely — tools become available to the agent immediately.
      </p>

      {/* Category pills */}
      <div className="flex flex-wrap gap-2">
        {CONNECTION_CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              activeCategory === cat
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-muted-foreground hover:border-input hover:bg-muted",
            )}
          >
            {cat}
          </button>
        ))}
      </div>

      {error && (
        <div className="border-destructive/30 bg-destructive/10 text-destructive rounded-lg border px-4 py-2 text-xs">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-muted-foreground py-12 text-center text-sm">
          Loading connectors…
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((tk) => (
            <div
              key={tk.slug}
              className="group border-border bg-card flex flex-col gap-3 rounded-xl border p-5 transition-shadow hover:shadow-md"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="border-border bg-muted flex size-10 items-center justify-center overflow-hidden rounded-xl border">
                    <IntegrationIcon slug={tk.slug} size={24} label={tk.name} />
                  </div>
                  <div>
                    <p className="text-foreground text-sm font-semibold">
                      {tk.name}
                    </p>
                    {tk.status === "connected" && tk.account_display && (
                      <p className="text-muted-foreground text-[11px]">
                        {tk.account_display}
                      </p>
                    )}
                  </div>
                </div>
                <span className="border-border bg-muted text-muted-foreground rounded-full border px-2 py-0.5 text-[10px]">
                  {tk.category}
                </span>
              </div>

              <p className="text-muted-foreground text-xs leading-relaxed">
                {tk.description}
              </p>

              <div className="mt-auto flex items-center gap-2 pt-1">
                {tk.status === "connected" ? (
                  confirmDisconnect === tk.slug ? (
                    <div className="flex flex-1 items-center gap-2">
                      <Button
                        size="sm"
                        variant="destructive"
                        className="flex-1 text-xs"
                        disabled={busy === tk.slug}
                        onClick={() => void handleDisconnect(tk.slug)}
                      >
                        {busy === tk.slug ? "…" : "Confirm disconnect"}
                      </Button>
                      <button
                        onClick={() => setConfirmDisconnect(null)}
                        className="border-border text-muted-foreground hover:bg-muted rounded-lg border px-2 py-1 text-xs"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <div className="flex flex-1 items-center gap-2">
                      <span className="text-success flex flex-1 items-center gap-1.5 text-xs font-medium">
                        <CheckCircle2Icon className="size-3.5" />
                        Connected
                      </span>
                      <button
                        onClick={() => setConfirmDisconnect(tk.slug)}
                        className="border-border text-muted-foreground hover:bg-destructive/10 hover:text-destructive rounded-lg border px-2.5 py-1 text-xs"
                      >
                        Disconnect
                      </button>
                    </div>
                  )
                ) : tk.status === "pending" ? (
                  <Button size="sm" className="flex-1 text-xs" disabled>
                    <Loader2Icon className="mr-1 size-3 animate-spin" />
                    Connecting…
                  </Button>
                ) : tk.status === "error" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    className="flex-1 text-xs"
                    disabled={busy === tk.slug}
                    onClick={() => void handleConnect(tk.slug)}
                  >
                    <RotateCwIcon className="mr-1 size-3" />
                    Retry
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    className="flex-1 text-xs"
                    disabled={busy === tk.slug}
                    onClick={() => void handleConnect(tk.slug)}
                  >
                    <PlugIcon className="mr-1 size-3" />
                    Connect
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
