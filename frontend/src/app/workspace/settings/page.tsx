import { redirect } from "next/navigation";

// The first section on the board.
export default function SettingsIndex() {
  redirect("/workspace/settings/account");
}
