"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { disconnectComposioToolkit } from "@/core/mcp/api";
import { connectComposioToolkit } from "@/core/mcp/connect";
import { useEnableMCPServer } from "@/core/mcp/hooks";
import { describeState, type Tone } from "@/core/tool-sources/logic";
import type { ToolSource } from "@/core/tool-sources/types";

const BADGE: Record<Tone, "default" | "secondary" | "destructive" | "outline"> =
  {
    ok: "default",
    off: "secondary",
    problem: "destructive",
    unknown: "outline",
  };

/** One tool source: its status, what that means, and connect/disconnect. */
export function ConnectionRow({
  source,
  configured,
}: {
  source: ToolSource;
  /** For a local server: whether extensions_config has an entry to toggle. */
  configured: boolean;
}) {
  const description = describeState(source);
  const queryClient = useQueryClient();
  const enable = useEnableMCPServer();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const name = source.id.slice(source.id.indexOf(":") + 1);

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setProblem(null);
    try {
      await work();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      setConfirming(false);
      void queryClient.invalidateQueries({ queryKey: ["toolSources"] });
      void queryClient.invalidateQueries({ queryKey: ["mcpConfig"] });
    }
  };

  let action: React.ReactNode = null;
  if (source.kind === "local" && configured) {
    const on = source.state !== "disabled";
    action = (
      <Button
        size="sm"
        variant="outline"
        disabled={busy}
        onClick={() =>
          run(() => enable.mutateAsync({ serverName: name, enabled: !on }))
        }
      >
        {on ? "Turn off" : "Turn on"}
      </Button>
    );
  } else if (source.kind === "connector" && source.state === "not-authorised") {
    action = (
      <Button
        size="sm"
        variant="outline"
        disabled={busy}
        onClick={() => run(() => connectComposioToolkit(name))}
      >
        Connect
      </Button>
    );
  } else if (source.kind === "connector") {
    action = confirming ? (
      <span className="flex items-center gap-2">
        <Button
          size="sm"
          variant="destructive"
          disabled={busy}
          onClick={() => run(() => disconnectComposioToolkit(name))}
        >
          Disconnect {source.name}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
          Keep
        </Button>
      </span>
    ) : (
      <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
        Disconnect
      </Button>
    );
  }

  return (
    <li
      className="border-border flex flex-col gap-2 rounded-md border p-3"
      data-testid="tool-source"
      data-source={source.id}
      data-state={source.state}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-foreground font-medium">{source.name}</span>
        <span className="flex items-center gap-2">
          <Badge variant={BADGE[description.tone]}>{description.label}</Badge>
          {action}
        </span>
      </div>
      <p className="text-muted-foreground text-sm">{description.meaning}</p>
      {source.kind === "local" && !configured && (
        <p className="text-muted-foreground text-xs">
          Add it under MCP servers below to turn it on.
        </p>
      )}
      {source.error && (
        <p className="text-destructive text-xs" data-testid="source-error">
          {source.error}
        </p>
      )}
      {problem && (
        <p className="text-destructive text-xs" data-testid="action-error">
          {problem}
        </p>
      )}
    </li>
  );
}
