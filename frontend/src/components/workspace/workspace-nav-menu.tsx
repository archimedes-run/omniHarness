"use client";

import {
  ActivityIcon,
  BrainIcon,
  BugIcon,
  EllipsisIcon,
  GlobeIcon,
  InfoIcon,
  MailIcon,
  PaletteIcon,
  Settings2Icon,
  ShieldIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSidebar } from "@/components/ui/sidebar";
import { avatarInitials } from "@/core/agents";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { usePolicyRules } from "@/core/policy/hooks";
import { usePreferences } from "@/core/preferences";
import { cn } from "@/lib/utils";

import { GithubIcon } from "./github-icon";

/** The email's part before "@": the gateway's own fallback for a display
 * name, used here while preferences load or when they cannot be read. */
function emailPrefix(email: string | undefined): string {
  return (email ?? "").split("@")[0] ?? "";
}

/**
 * The sidebar footer: the signed-in user, and More (Settings, Memory, Safety,
 * Activity log, Appearance, About, then the project's links).
 */
export function WorkspaceNavMenu() {
  const [mounted, setMounted] = useState(false);
  // Something inside More needs attention: the policy rules in force were not
  // the ones last written (a refused edit) or could not be read at all. The
  // dot says "look in here" without opening the menu (Phase 2.6).
  const { rules } = usePolicyRules();
  const attention = rules?.kept_previous === true || rules?.unreadable === true;
  const { open: isSidebarOpen } = useSidebar();
  const { t } = useI18n();
  const { user } = useAuth();
  // The display name the user chose, or the gateway's fallback for it
  // (display_name_effective).
  const { displayName } = usePreferences();
  const name = displayName ?? emailPrefix(user?.email);

  useEffect(() => {
    setMounted(true);
  }, []);

  const dot = attention && (
    <span
      className="bg-destructive absolute -top-0.5 -right-0.5 size-2 rounded-full"
      data-testid="more-attention"
      aria-label="Something in More needs attention"
    />
  );

  const trigger = (
    <button
      type="button"
      aria-label={t.sidebar.moreLabel}
      data-testid="more-button"
      className={cn(
        "border-sidebar-border text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-sidebar-ring data-[state=open]:bg-sidebar-accent relative flex h-11 shrink-0 items-center justify-center gap-1.5 rounded-md border px-2.5 text-sm outline-none focus-visible:ring-2 md:h-8",
        !isSidebarOpen && "md:size-8 md:px-0",
        !mounted && "pointer-events-none",
      )}
    >
      {isSidebarOpen ? (
        <span>{t.sidebar.more}</span>
      ) : (
        <EllipsisIcon className="size-4" />
      )}
      {dot}
    </button>
  );

  const section = (
    href: string,
    Icon: typeof InfoIcon,
    label: string,
    testId: string,
  ) => (
    <DropdownMenuItem asChild>
      <Link href={href} data-testid={testId} className="max-md:min-h-11">
        <Icon />
        {label}
        {testId === "more-settings" && attention && (
          <span
            className="bg-destructive ml-auto size-1.5 rounded-full"
            aria-label="needs attention"
          />
        )}
      </Link>
    </DropdownMenuItem>
  );

  const external = (href: string, Icon: typeof InfoIcon, label: string) => (
    <DropdownMenuItem asChild>
      <a
        href={href}
        target={href.startsWith("mailto:") ? undefined : "_blank"}
        rel="noopener noreferrer"
        className="max-md:min-h-11"
      >
        <Icon />
        {label}
      </a>
    </DropdownMenuItem>
  );

  return (
    <div
      className={cn(
        "border-sidebar-border flex items-center gap-2 border-t pt-2",
        !isSidebarOpen && "justify-center border-t-0",
      )}
      data-testid="sidebar-user"
    >
      {isSidebarOpen && (
        <>
          <Avatar className="size-7">
            <AvatarFallback className="bg-primary-subtle text-foreground text-[13px] font-semibold">
              {avatarInitials(name)}
            </AvatarFallback>
          </Avatar>
          <span
            className="text-sidebar-foreground min-w-0 flex-1 truncate text-sm"
            data-testid="sidebar-user-name"
            title={user?.email}
          >
            {name}
          </span>
        </>
      )}
      {mounted ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
          <DropdownMenuContent
            className="min-w-56 rounded-lg"
            align="end"
            side="top"
            sideOffset={4}
          >
            <DropdownMenuGroup>
              {section(
                "/workspace/settings",
                Settings2Icon,
                t.common.settings,
                "more-settings",
              )}
              {section(
                "/workspace/settings/memory",
                BrainIcon,
                t.sidebar.memory,
                "more-memory",
              )}
              {section(
                "/workspace/settings/safety",
                ShieldIcon,
                t.sidebar.safety,
                "more-safety",
              )}
              {section(
                "/workspace/settings/activity",
                ActivityIcon,
                t.sidebar.activityLog,
                "more-activity",
              )}
              {section(
                "/workspace/settings/appearance",
                PaletteIcon,
                t.sidebar.appearance,
                "more-appearance",
              )}
              {section(
                "/workspace/settings/about",
                InfoIcon,
                t.sidebar.about,
                "more-about",
              )}
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              {external(
                "https://omniharness.tech/",
                GlobeIcon,
                t.workspace.officialWebsite,
              )}
              {external(
                "https://github.com/archimedes-run/omniHarness",
                GithubIcon as typeof InfoIcon,
                t.workspace.visitGithub,
              )}
              {external(
                "https://github.com/archimedes-run/omniHarness/issues",
                BugIcon,
                t.workspace.reportIssue,
              )}
              {external(
                "mailto:support@omniharness.tech",
                MailIcon,
                t.workspace.contactUs,
              )}
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        trigger
      )}
    </div>
  );
}
