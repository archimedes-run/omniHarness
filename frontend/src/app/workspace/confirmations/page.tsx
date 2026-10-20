import { redirect } from "next/navigation";

// Pending confirmations moved to the Inbox (Phase 2.5), now Home (006).
export default function MovedPage() {
  redirect("/workspace/home");
}
