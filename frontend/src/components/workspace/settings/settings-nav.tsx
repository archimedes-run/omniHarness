"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useI18n } from "@/core/i18n/hooks";
import { usePolicyRules } from "@/core/policy/hooks";
import { cn } from "@/lib/utils";

/** The board's order (Feature 006 "Settings"). Tools and Skills keep their
 * routes (/workspace/settings/tools, /skills: the command palette links the
 * latter) but are not listed: MCP Suite and the Skills panel own them now. */
export const SETTINGS_SECTIONS = [
  "account",
  "memory",
  "safety",
  "notification",
  "activity",
  "appearance",
  "about",
] as const;
export type SettingsSectionId = (typeof SETTINGS_SECTIONS)[number];

export function settingsHref(section: SettingsSectionId) {
  return `/workspace/settings/${section}`;
}

/** The settings sub-navigation: one page per section, so each section's code
 * loads with its route. */
export function SettingsNav() {
  const { t } = useI18n();
  const pathname = usePathname();
  // The rules in force are not the ones last written, or cannot be read:
  // Safety says so without being opened.
  const { rules } = usePolicyRules();
  const attention = rules?.kept_previous === true || rules?.unreadable === true;
  const label: Record<SettingsSectionId, string> = {
    account: t.settings.sections.account,
    memory: t.settings.sections.memory,
    safety: "Safety",
    notification: "Notifications",
    activity: "Activity log",
    appearance: t.settings.sections.appearance,
    about: t.settings.sections.about,
  };
  return (
    <nav aria-label="Settings" className="flex flex-col gap-0.5">
      {SETTINGS_SECTIONS.map((id) => {
        const active = pathname === settingsHref(id);
        return (
          <Link
            key={id}
            href={settingsHref(id)}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm max-md:min-h-11",
              active
                ? "bg-surface-raised text-foreground font-medium"
                : "text-foreground-2 hover:bg-accent hover:text-foreground",
            )}
          >
            <span className="flex-1">{label[id]}</span>
            {id === "safety" && attention && (
              <span
                className="bg-destructive size-1.5 rounded-full"
                role="img"
                aria-label="needs attention"
              />
            )}
          </Link>
        );
      })}
    </nav>
  );
}
