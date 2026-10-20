import { redirect } from "next/navigation";

/** Inbox left the sidebar (Feature 006): what is waiting on you is on Home. */
export default function InboxPage() {
  redirect("/workspace/home");
}
