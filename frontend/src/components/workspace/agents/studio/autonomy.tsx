"use client";

import Link from "next/link";
import { useState } from "react";

import { useGrantUses, type AutonomyView } from "@/core/studio";

import { useStudioCopy } from "./copy";
import { formatWhen } from "./runs";
import { TabPanel } from "./studio-frame";

/**
 * Autonomy (Agent-Studio.dc.html, design-notes #12 to #14): the reversible
 * actions the agent may take on its own in a scheduled run, each with what it
 * allows in plain words. What the server says cannot be granted is shown
 * disabled with its reason; "Always waits for you" is generated from the
 * rules in force. Nothing here is saved until Save.
 */
export function AutonomyTab({
  agentId,
  autonomy,
  error,
  granted,
  onChange,
}: {
  agentId: string | null;
  autonomy: AutonomyView | undefined;
  error: unknown;
  granted: string[];
  onChange: (granted: string[]) => void;
}) {
  const c = useStudioCopy().agents;
  const [all, setAll] = useState(false);
  const waits = autonomy?.always_waits ?? [];
  const shown = all ? waits : waits.slice(0, 8);

  return (
    <TabPanel value="autonomy" className="flex flex-col gap-3.5 outline-none">
      <p className="text-foreground-2 m-0">{c.autonomyIntro}</p>
      {!agentId ? (
        <p className="text-muted-foreground">{c.saveAgentFirst}</p>
      ) : error ? (
        <p className="text-destructive" role="alert">
          {c.autonomyUnreadable(String((error as Error).message))}
        </p>
      ) : (
        <>
          <fieldset
            className="border-border-strong m-0 flex flex-col gap-2.5 rounded-xl border px-4 py-3"
            data-testid="autonomy-grants"
          >
            <legend className="px-1.5 text-[13px]">{c.mayDoLegend}</legend>
            {(autonomy?.classes ?? []).map((cls) => (
              <label
                key={cls.id}
                className="flex min-h-11 items-start gap-2.5 md:min-h-0"
                data-testid={`grant-${cls.id}`}
              >
                <input
                  type="checkbox"
                  className="accent-primary mt-0.5 size-[18px] shrink-0"
                  checked={granted.includes(cls.id)}
                  disabled={!cls.grantable}
                  onChange={(e) =>
                    onChange(
                      e.target.checked
                        ? [...granted, cls.id]
                        : granted.filter((g) => g !== cls.id),
                    )
                  }
                />
                <span>
                  <span className="block">{cls.label}</span>
                  <span className="text-muted-foreground block text-xs">
                    {cls.grantable
                      ? cls.allows
                      : c.grantWhy(cls.not_grantable_reason)}
                  </span>
                </span>
              </label>
            ))}
            <label className="flex items-start gap-2.5">
              <input
                type="checkbox"
                className="accent-primary mt-0.5 size-[18px] shrink-0"
                checked
                disabled
                aria-describedby="drafts-note"
              />
              <span id="drafts-note" className="text-foreground-2">
                {c.draftsAlways}
              </span>
            </label>
            {autonomy ? (
              <p className="text-muted-foreground m-0 text-xs">
                {c.capNote(autonomy.cap_per_run)}
              </p>
            ) : null}
          </fieldset>
          <div
            className="bg-card border-border-strong text-foreground-2 rounded-xl border px-4 py-3"
            data-testid="always-waits"
          >
            <p className="m-0">
              <span className="text-foreground font-medium">
                {c.alwaysWaits}:
              </span>{" "}
              {c.alwaysWaitsLead}
            </p>
            <p className="mt-1.5 font-mono text-xs leading-relaxed">
              {shown.join(", ")}
            </p>
            {waits.length > 8 ? (
              <button
                type="button"
                className="text-primary mt-1 min-h-11 text-xs underline-offset-2 hover:underline md:min-h-0"
                onClick={() => setAll((v) => !v)}
              >
                {all ? c.showFewer : c.showAll(waits.length)}
              </button>
            ) : null}
          </div>
        </>
      )}
    </TabPanel>
  );
}

/** What the agent did on its own under its grants, newest first, each with
 * what caused it (the run's history of granted actions). */
export function DoneOnItsOwn({ agentId }: { agentId: string }) {
  const c = useStudioCopy().agents;
  const { uses, error } = useGrantUses(agentId);
  return (
    <div data-testid="done-on-its-own">
      <div className="text-muted-foreground mb-1.5 text-xs">
        {c.doneOnItsOwn}
      </div>
      {error ? (
        <p className="text-muted-foreground border-border border-t py-2.5">
          {c.usesUnreadable}
        </p>
      ) : uses?.length === 0 ? (
        <p className="text-muted-foreground border-border border-t py-2.5">
          {c.nothingDone}
        </p>
      ) : (
        (uses ?? []).slice(0, 10).map((u, i) => (
          <div
            key={`${u.at}-${i}`}
            className="border-border flex flex-wrap gap-3 border-t py-2.5"
            data-testid="grant-use"
          >
            <span className="text-muted-foreground w-[120px] shrink-0">
              {formatWhen(u.at, c)}
            </span>
            <span className="min-w-0 flex-1">
              {u.targets.join("; ")}
              <span className="text-muted-foreground">{` · ${c.because(u.origin, u.origin_source)}`}</span>
            </span>
            {u.thread_id ? (
              <Link
                href={`/workspace/chats/${encodeURIComponent(u.thread_id)}`}
                className="text-primary underline underline-offset-2"
              >
                {c.open}
              </Link>
            ) : null}
          </div>
        ))
      )}
    </div>
  );
}
