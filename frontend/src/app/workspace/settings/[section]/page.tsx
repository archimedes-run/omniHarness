"use client";

import dynamic from "next/dynamic";
import { notFound, useParams, useRouter } from "next/navigation";

// The sections that were the settings dialog. Each loads on its own route:
// Memory and About render markdown, which no other page should pay for.
const SECTIONS = {
  account: dynamic(() =>
    import("@/components/workspace/settings/account-settings-page").then(
      (m) => m.AccountSettingsPage,
    ),
  ),
  appearance: dynamic(() =>
    import("@/components/workspace/settings/appearance-settings-page").then(
      (m) => m.AppearanceSettingsPage,
    ),
  ),
  notification: dynamic(() =>
    import("@/components/workspace/settings/notification-settings-page").then(
      (m) => m.NotificationSettingsPage,
    ),
  ),
  memory: dynamic(() =>
    import("@/components/workspace/settings/memory/memory-page").then(
      (m) => m.MemoryPage,
    ),
  ),
  tools: dynamic(() =>
    import("@/components/workspace/settings/tool-settings-page").then(
      (m) => m.ToolSettingsPage,
    ),
  ),
  skills: dynamic(() =>
    import("@/components/workspace/settings/skill-settings-page").then(
      (m) => m.SkillSettingsPage,
    ),
  ),
  about: dynamic(() =>
    import("@/components/workspace/settings/about-settings-page").then(
      (m) => m.AboutSettingsPage,
    ),
  ),
} as const;

export default function SettingsSectionPage() {
  const { section } = useParams<{ section: string }>();
  const router = useRouter();
  const Section = SECTIONS[section as keyof typeof SECTIONS];
  if (!Section) notFound();
  return (
    <div className="mx-auto w-full max-w-3xl p-6">
      {section === "skills" ? (
        <Section onClose={() => router.push("/workspace/chats/new")} />
      ) : (
        <Section />
      )}
    </div>
  );
}
