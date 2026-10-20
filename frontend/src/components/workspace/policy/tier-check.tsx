"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTierCheck } from "@/core/policy/hooks";

export function TierCheckForm() {
  const [tool, setTool] = useState("");
  const [args, setArgs] = useState("{}");
  const check = useTierCheck();
  const result = check.data;

  return (
    <section
      className="bg-card border-border space-y-2 rounded-xl border px-[18px] py-4"
      aria-labelledby="check-heading"
    >
      <h2 id="check-heading" className="text-[15px] font-semibold">
        Check a tool&apos;s tier
      </h2>
      <p className="text-muted-foreground text-xs">
        Classifies a call exactly as dispatch would, and runs nothing.
      </p>
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault();
          if (tool.trim()) check.mutate({ tool: tool.trim(), args });
        }}
      >
        <Input
          aria-label="Tool name"
          placeholder="calendar_delete_event"
          value={tool}
          onChange={(e) => setTool(e.target.value)}
        />
        <Input
          aria-label="Arguments (JSON)"
          placeholder="{}"
          value={args}
          onChange={(e) => setArgs(e.target.value)}
        />
        <Button type="submit" disabled={!tool.trim() || check.isPending}>
          Check
        </Button>
      </form>
      {check.error != null && (
        <p className="text-destructive text-sm" data-testid="check-error">
          {String(check.error)}
        </p>
      )}
      {/* FR-023: absent is not a tier. No tool exists, so say that. */}
      {result?.absent && (
        <p
          className="border-border text-foreground rounded-md border p-3 text-sm"
          data-testid="absent"
        >
          {result.absent}
        </p>
      )}
      {result && !result.absent && (
        <div
          className="border-border space-y-1 rounded-md border p-3"
          data-testid="tier-result"
          data-tier={result.tier}
          data-from-default={String(result.from_default)}
        >
          <div className="flex items-center gap-2">
            <span className="text-foreground font-medium">{result.tool}</span>
            {/* 007: a tool no rule names has no tier; it is refused. */}
            {result.refused ? (
              <Badge variant="destructive" data-testid="refused-marker">
                No policy rule — refused
              </Badge>
            ) : (
              <Badge variant={result.tier === 3 ? "destructive" : "secondary"}>
                Tier {result.tier}
              </Badge>
            )}
            {/* FR-027: the default is not a classification, and says so. */}
            {result.from_default && !result.refused && (
              <Badge variant="outline" data-testid="default-marker">
                Default — no rule matched
              </Badge>
            )}
          </div>
          <p
            className="text-muted-foreground text-sm"
            data-testid="deciding-rule"
          >
            {result.deciding_rule
              ? `Decided by: ${result.deciding_rule}`
              : result.refused
                ? "No rule names this tool, so it is refused: never offered to the assistant, never run."
                : "No rule matched this tool, and the rules could not be read, so every tool is Tier 3."}
          </p>
          {result.in_plain_words && (
            <p className="text-foreground text-sm" data-testid="plain-words">
              {result.in_plain_words}
            </p>
          )}
          {result.raised_by && (
            <p
              className="text-muted-foreground text-sm"
              data-testid="raised-by"
            >
              Raised to Tier {result.raised_by.tier} by an exception when{" "}
              {JSON.stringify(result.raised_by.when)}.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
