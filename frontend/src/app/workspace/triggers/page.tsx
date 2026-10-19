import { redirect } from "next/navigation";

// Phase 2.5 navigation: Trigger rules moved to Automations (their firing log is in Settings → Activity log).
export default function MovedPage() {
  redirect("/workspace/automations");
}
