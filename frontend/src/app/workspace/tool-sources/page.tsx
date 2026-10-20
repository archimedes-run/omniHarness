import { redirect } from "next/navigation";

// Phase 2.5 navigation: Tool sources moved to Settings → Connections.
export default function MovedPage() {
  redirect("/workspace/connections");
}
