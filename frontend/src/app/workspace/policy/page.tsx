import { redirect } from "next/navigation";

// Phase 2.5 navigation: The policy inspector moved to Settings → Safety.
export default function MovedPage() {
  redirect("/workspace/settings/safety");
}
