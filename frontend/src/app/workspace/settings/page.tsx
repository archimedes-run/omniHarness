import { redirect } from "next/navigation";

export default function SettingsIndex() {
  redirect("/workspace/settings/connections");
}
