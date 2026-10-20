import { redirect } from "next/navigation";

// Phase 2.6: Connections is a sidebar item again, not a settings section.
export default function MovedPage() {
  redirect("/workspace/connections");
}
