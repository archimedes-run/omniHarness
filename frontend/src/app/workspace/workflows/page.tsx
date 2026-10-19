import { redirect } from "next/navigation";

// Phase 2.5 navigation: Workflows are listed in Automations; their detail pages stay under /workspace/workflows/[id].
export default function MovedPage() {
  redirect("/workspace/automations");
}
