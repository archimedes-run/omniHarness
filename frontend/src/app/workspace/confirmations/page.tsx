import { redirect } from "next/navigation";

// Phase 2.5 navigation: Pending confirmations moved to the Inbox.
export default function MovedPage() {
  redirect("/workspace/inbox");
}
