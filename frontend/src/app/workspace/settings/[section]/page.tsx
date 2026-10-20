"use client";

import dynamic from "next/dynamic";
import { notFound, useParams, useRouter } from "next/navigation";

import { PageColumn, PageHeader } from "@/components/workspace/page-kit";

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

/** The page heading of each section that does not draw its own (Memory does). */
const HEADINGS: Partial<Record<keyof typeof SECTIONS, [string, string]>> = {
  account: ["Account", "Your name, and how you sign in."],
  appearance: ["Appearance", "How the workspace looks, in light and dark."],
  notification: [
    "Notifications",
    "How OmniHarness reaches you when something needs you.",
  ],
  about: ["About", "What OmniHarness is, and what it is built on."],
  tools: ["Tools", "The tools agents can use, from each source."],
  skills: ["Skills", "The skills agents can use."],
};

export default function SettingsSectionPage() {
  const { section } = useParams<{ section: string }>();
  const router = useRouter();
  const Section = SECTIONS[section as keyof typeof SECTIONS];
  if (!Section) notFound();
  return (
    <PageColumn width="narrow">
      {HEADINGS[section as keyof typeof SECTIONS] && (
        <PageHeader
          title={HEADINGS[section as keyof typeof SECTIONS]![0]}
          description={HEADINGS[section as keyof typeof SECTIONS]![1]}
        />
      )}
      {section === "skills" ? (
        <Section onClose={() => router.push("/workspace/chats/new")} />
      ) : (
        <Section />
      )}
    </PageColumn>
  );
}
