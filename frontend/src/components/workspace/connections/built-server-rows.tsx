"use client";

import Link from "next/link";

import { StatusWord } from "@/components/workspace/page-kit";
import { useBuiltServers } from "@/core/mcp-studio/hooks";

import { buildStateTone } from "./build-state";

/**
 * Servers built by an agent that are not (yet) in the MCP config, as rows of
 * the Connected tab's MCP servers list. Unreadable (the builder is off, or the
 * gateway did not answer), they are simply not listed: the configured servers
 * above are the ones agents can use.
 */
export function BuiltServerRows({ exclude }: { exclude: Set<string> }) {
  const { servers } = useBuiltServers();
  return (
    <>
      {servers
        ?.filter((s) => !exclude.has(s.name.toLowerCase()))
        .map((s) => (
          <li
            key={s.id}
            className="flex flex-wrap items-center gap-3.5 px-[18px] py-3"
            data-testid="built-server-row"
            data-state={s.state ?? "unknown"}
          >
            <span className="min-w-0 flex-[1_1_200px] font-mono text-[13px]">
              <Link
                href={`/workspace/connections?tab=build&server=${s.id}`}
                className="hover:underline"
              >
                {s.name}
              </Link>{" "}
              <span className="text-muted-foreground font-sans text-xs">
                · built by an agent
              </span>
            </span>
            <span className="text-muted-foreground w-[110px] text-xs">
              Sandbox
            </span>
            <span className="text-muted-foreground w-[70px] text-xs">
              {s.tool_count == null ? "— tools" : `${s.tool_count} tools`}
            </span>
            <StatusWord tone={buildStateTone(s.state)} className="w-[90px]">
              {s.state_label ?? s.status}
            </StatusWord>
            <span className="w-8" />
          </li>
        ))}
    </>
  );
}
