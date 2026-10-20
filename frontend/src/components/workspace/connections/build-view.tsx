"use client";

import { McpSuite } from "@/components/workspace/mcp/mcp-suite";

/** MCP Suite > Build. Interim: the previous suite, until the Build flow lands. */
export function BuildView(_: { selected: string | null }) {
  return <McpSuite />;
}
