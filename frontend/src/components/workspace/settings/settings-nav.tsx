"use client";

import {
  ActivityIcon,
  BellIcon,
  BrainIcon,
  InfoIcon,
  PaletteIcon,
  PlugIcon,
  ShieldIcon,
  SparklesIcon,
  UserIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export const SETTINGS_SECTIONS = [
  "connections",
  "safety",
  "activity",
  "account",
  "appearance",
  "notification",
  "memory",
  "tools",
  "skills",
  "about",
] as const;
export type SettingsSectionId = (typeof SETTINGS_SECTIONS)[number];

const ICONS: Record<SettingsSectionId, LucideIcon> = {
  connections: PlugIcon,
  safety: ShieldIcon,
  activity: ActivityIcon,
  account: UserIcon,
  appearance: PaletteIcon,
  notification: BellIcon,
  memory: BrainIcon,
  tools: WrenchIcon,
  skills: SparklesIcon,
  about: InfoIcon,
};

export function settingsHref(section: SettingsSectionId) {
  return `/workspace/settings/${section}`;
}

/** The settings sub-navigation: one page per section, so each section's code
 * loads with its route (the old dialog loaded all of them, everywhere). */
export function SettingsNav() {
  const { t } = useI18n();
  const pathname = usePathname();
  const label: Record<SettingsSectionId, string> = {
    connections: "Connections",
    safety: "Safety",
    activity: "Activity log",
    account: t.settings.sections.account,
    appearance: t.settings.sections.appearance,
    notification: t.settings.sections.notification,
    memory: t.settings.sections.memory,
    tools: t.settings.sections.tools,
    skills: t.settings.sections.skills,
    about: t.settings.sections.about,
  };
  return (
    <nav aria-label="Settings" className="flex flex-col gap-0.5">
      {SETTINGS_SECTIONS.map((id) => {
        const Icon = ICONS[id];
        const active = pathname === settingsHref(id);
        return (
          <Link
            key={id}
            href={settingsHref(id)}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-2 text-sm",
              active
                ? "bg-accent text-accent-foreground font-medium"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon className="size-4" />
            {label[id]}
          </Link>
        );
      })}
    </nav>
  );
}
