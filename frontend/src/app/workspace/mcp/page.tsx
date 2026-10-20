import { redirect } from "next/navigation";

// Phase 2.5 navigation: The MCP Suite moved to Settings → Connections; server detail pages stay under /workspace/mcp/[id].
export default function MovedPage() {
  redirect("/workspace/connections");
}
