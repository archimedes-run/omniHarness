import { redirect } from "next/navigation";

// Feature 006: the tool sources are listed in Settings > Safety (and managed
// in MCP Suite).
export default function MovedPage() {
  redirect("/workspace/settings/safety");
}
