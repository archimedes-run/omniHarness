"use client";

import Link from "next/link";

import { BrandLogo } from "@/components/brand";
import { sourceStatus } from "@/components/workspace/connections/connected-logic";
import {
  RowList,
  SectionHeading,
  StatusWord,
} from "@/components/workspace/page-kit";
import { useToolSources } from "@/core/tool-sources/hooks";
import { formatTimeAgo } from "@/core/utils/datetime";

/**
 * Settings > Safety > Tool sources (Feature 006; was /workspace/tool-sources):
 * every source the agents' tools come from, its state, its real error, and
 * what calls through it were OBSERVED to do (last worked, last failed). A
 * source never called says so; an unreadable list says it cannot tell.
 */
export function SafetyToolSources() {
  const { view, isLoading, error } = useToolSources();
  return (
    <section
      aria-labelledby="sources-heading"
      className="flex flex-col gap-3"
      data-testid="safety-tool-sources"
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <SectionHeading id="sources-heading" className="flex-1">
          Tool sources
        </SectionHeading>
        <Link
          href="/workspace/connections"
          className="text-primary text-sm hover:underline"
        >
          Manage in MCP Suite
        </Link>
      </div>
      <p className="text-muted-foreground text-sm">
        Where each tool comes from, whether it loads, and what calls through it
        were seen to do.
      </p>
      {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
      {error != null && (
        <p
          className="text-destructive text-sm"
          data-testid="sources-unreadable"
        >
          I can&apos;t tell which tool sources are working: {String(error)}
        </p>
      )}
      {view && (
        <RowList>
          {view.sources.map((source) => {
            const status = sourceStatus(source);
            const reason = source.error ?? null;
            return (
              <li
                key={source.id}
                className="flex flex-wrap items-center gap-3 px-[18px] py-3"
                data-testid="safety-source"
                data-source={source.id}
                data-state={source.state}
              >
                <BrandLogo source={source.id} name={source.name} size={24} />
                <span className="min-w-0 flex-[1_1_180px]">
                  <span className="block font-medium">{source.name}</span>
                  <span className="text-muted-foreground block text-xs">
                    {observed(source.last_success_at, source.last_failure_at)}
                  </span>
                </span>
                <span className="text-muted-foreground w-[70px] text-xs">
                  {source.kind === "connector" ? "App" : "MCP server"}
                </span>
                <StatusWord tone={status.tone} className="w-[96px]">
                  {status.label}
                </StatusWord>
                {(reason !== null ||
                  source.last_error_withheld === true ||
                  Boolean(source.last_error)) && (
                  <p
                    className="text-muted-foreground basis-full font-mono text-xs break-all"
                    data-testid="safety-source-error"
                  >
                    {reason ??
                      (source.last_error_withheld
                        ? "Withheld: the last error could not be shown safely."
                        : `Last error: ${source.last_error}`)}
                  </p>
                )}
              </li>
            );
          })}
        </RowList>
      )}
    </section>
  );
}

/** What calls were observed to do, in words. Never seen is said, not hidden. */
function observed(
  ok: string | null | undefined,
  failed: string | null | undefined,
): string {
  if (ok === undefined && failed === undefined) return "Calls not tracked";
  if (!ok && !failed) return "No call seen yet";
  const parts: string[] = [];
  if (ok) parts.push(`worked ${formatTimeAgo(ok)} (observed)`);
  if (failed) parts.push(`failed ${formatTimeAgo(failed)} (observed)`);
  return parts.join(" · ");
}
