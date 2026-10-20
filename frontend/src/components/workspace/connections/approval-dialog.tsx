"use client";

import { useEffect, useState, type RefObject } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { approveAndEnable, getApprovalPacket } from "@/core/mcp-studio/api";
import type { ApprovalPacket, BuiltServer } from "@/core/mcp-studio/types";
import { cn } from "@/lib/utils";

type Tier = 1 | 2 | 3;

const TIER_MEANING: Record<Tier, string> = {
  1: "Runs silently",
  2: "Runs, then tells you",
  3: "Asks every time",
};

/**
 * #59: "Review and approve". The approval names the code by its hash and is
 * only possible after the code was shown: opening this dialog fetches the
 * full code (with a single-use view token) and shows it first. Every tool
 * starts at Tier 3 until you set it here.
 */
export function ApprovalDialog({
  server,
  open,
  onOpenChange,
  onApproved,
  returnFocusTo,
}: {
  server: BuiltServer;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApproved: () => void;
  /** Focus goes back here when the dialog closes. */
  returnFocusTo?: RefObject<HTMLButtonElement | null>;
}) {
  const [packet, setPacket] = useState<ApprovalPacket | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [codeShown, setCodeShown] = useState(false);
  const [tab, setTab] = useState("code");
  const [tiers, setTiers] = useState<Record<string, Tier>>({});

  const load = async () => {
    setProblem(null);
    setPacket(null);
    setCodeShown(false);
    setTab("code");
    try {
      const next = await getApprovalPacket(server.id);
      setPacket(next);
      setTiers(
        Object.fromEntries(
          next.tools.map((t) => [t.name, (t.proposed_tier ?? 3) as Tier]),
        ),
      );
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    if (open) void load();
    // Reload only when the dialog opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // The code is "shown" once the Code tab has rendered the packet's code.
  useEffect(() => {
    if (packet && tab === "code") setCodeShown(true);
  }, [packet, tab]);

  const changed =
    packet != null &&
    server.code_sha256 != null &&
    server.code_sha256 !== packet.code_sha256;

  const approve = async () => {
    if (!packet) return;
    setBusy(true);
    setProblem(null);
    try {
      await approveAndEnable(
        server.id,
        packet.code_sha256,
        packet.view_token,
        tiers,
      );
      onApproved();
      onOpenChange(false);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const lines = packet?.source_code.split("\n") ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="flex max-h-[90vh] flex-col sm:max-w-3xl"
        data-testid="approval-dialog"
        onCloseAutoFocus={(e) => {
          if (returnFocusTo?.current) {
            e.preventDefault();
            returnFocusTo.current.focus();
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>Review and approve {server.name}</DialogTitle>
          <DialogDescription>
            Approving lets this exact code run with your real keys. Any change
            to the code needs a new approval.
          </DialogDescription>
        </DialogHeader>

        {!packet && !problem && (
          <p className="text-muted-foreground text-sm">Loading the code…</p>
        )}

        {packet && (
          <>
            <p className="text-[13px]" data-testid="approval-hash">
              <span className="text-muted-foreground">Code hash </span>
              <code className="font-mono font-semibold">
                sha256:{packet.code_sha256.slice(0, 12)}
              </code>
              <code className="text-muted-foreground font-mono break-all">
                {packet.code_sha256.slice(12)}
              </code>
            </p>
            {packet.approved_version_on && (
              <p className="text-muted-foreground text-[13px]">
                The approved version is still on. This is new code.
              </p>
            )}
            {changed && (
              <p className="text-warning text-[13px]" role="alert">
                The code changed since you opened it.{" "}
                <button
                  type="button"
                  className="underline"
                  onClick={() => void load()}
                >
                  Load the new code
                </button>
              </p>
            )}
            <Tabs
              value={tab}
              onValueChange={setTab}
              className="flex min-h-0 flex-1 flex-col"
            >
              <TabsList>
                <TabsTrigger value="code">Code</TabsTrigger>
                <TabsTrigger value="hosts">
                  Outbound hosts ({packet.egress_hosts.length})
                </TabsTrigger>
                <TabsTrigger value="tools">
                  Tools and tiers ({packet.tools.length})
                </TabsTrigger>
              </TabsList>
              <TabsContent value="code" className="min-h-0 flex-1">
                <pre
                  className="bg-card border-border max-h-[50vh] overflow-auto rounded-lg border p-3 font-mono text-xs leading-5"
                  data-testid="approval-code"
                  tabIndex={0}
                  aria-label={`server.py, ${lines.length} lines`}
                >
                  {lines.map((line, i) => (
                    <div key={i} className="flex gap-3">
                      <span
                        className="text-muted-foreground w-8 flex-none text-right select-none"
                        aria-hidden
                      >
                        {i + 1}
                      </span>
                      <span className="whitespace-pre">{line}</span>
                    </div>
                  ))}
                </pre>
              </TabsContent>
              <TabsContent value="hosts">
                {packet.egress_hosts.length === 0 ? (
                  <p className="text-sm" data-testid="approval-hosts">
                    None: this tool can&apos;t reach the internet.
                  </p>
                ) : (
                  <ul
                    className="flex flex-col gap-1"
                    data-testid="approval-hosts"
                  >
                    {packet.egress_hosts.map((h) => (
                      <li key={h} className="font-mono text-[13px]">
                        {h}
                        <span className="text-muted-foreground">:443</span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="text-muted-foreground mt-2 text-[13px]">
                  Read from the code. Anything else it tries to reach is
                  blocked.
                </p>
                {packet.secret_names.length > 0 && (
                  <p className="mt-2 text-[13px]">
                    Keys it will receive:{" "}
                    {packet.secret_names.map((n) => (
                      <code key={n} className="mr-1 font-mono">
                        {n}
                      </code>
                    ))}
                  </p>
                )}
              </TabsContent>
              <TabsContent value="tools">
                <ul
                  className="flex flex-col gap-3"
                  data-testid="approval-tools"
                >
                  {packet.tools.map((t) => (
                    <li
                      key={t.name}
                      className="flex flex-wrap items-center gap-3"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block font-mono text-[13px]">
                          {t.name}
                        </span>
                        <span className="text-muted-foreground block text-xs">
                          {TIER_MEANING[tiers[t.name] ?? 3]}
                        </span>
                      </span>
                      <ToggleGroup
                        type="single"
                        variant="outline"
                        aria-label={`Tier for ${t.name}`}
                        value={String(tiers[t.name] ?? 3)}
                        onValueChange={(v) =>
                          v &&
                          setTiers((old) => ({
                            ...old,
                            [t.name]: Number(v) as Tier,
                          }))
                        }
                      >
                        {([1, 2, 3] as Tier[]).map((n) => (
                          <ToggleGroupItem
                            key={n}
                            value={String(n)}
                            aria-label={`Tier ${n}: ${TIER_MEANING[n]}`}
                            className="max-md:min-h-11 max-md:min-w-11"
                          >
                            {n}
                          </ToggleGroupItem>
                        ))}
                      </ToggleGroup>
                    </li>
                  ))}
                </ul>
              </TabsContent>
            </Tabs>
          </>
        )}

        {problem && (
          <p className="text-destructive text-[13px]" role="alert">
            {problem}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            className={cn("font-semibold")}
            disabled={!packet || !codeShown || busy || changed}
            aria-describedby={!codeShown ? "approve-needs-code" : undefined}
            onClick={() => void approve()}
            data-testid="approve-and-turn-on"
          >
            {busy ? "Turning on…" : "Approve and turn on"}
          </Button>
          {!codeShown && (
            <span id="approve-needs-code" className="sr-only">
              Open the code first
            </span>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
