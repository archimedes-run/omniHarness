"use client";

import {
  BugIcon,
  ChevronsUpDown,
  GlobeIcon,
  InfoIcon,
  MailIcon,
  Settings2Icon,
  EllipsisIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { usePolicyRules } from "@/core/policy/hooks";

import { GithubIcon } from "./github-icon";

function NavMenuButtonContent({
  isSidebarOpen,
  t,
  attention = false,
}: {
  isSidebarOpen: boolean;
  t: ReturnType<typeof useI18n>["t"];
  attention?: boolean;
}) {
  const dot = attention && (
    <span
      className="bg-destructive absolute top-1.5 left-5 size-1.5 rounded-full"
      data-testid="more-attention"
      aria-label="Something in More needs attention"
    />
  );
  return isSidebarOpen ? (
    <div className="relative flex w-full items-center gap-2 text-left text-sm text-inherit">
      <EllipsisIcon className="size-4" />
      {dot}
      <span>{t.workspace.settingsAndMore}</span>
      <ChevronsUpDown className="ml-auto size-4 text-current" />
    </div>
  ) : (
    <div className="relative flex size-full items-center justify-center">
      <EllipsisIcon className="size-4 text-current" />
      {dot}
    </div>
  );
}

export function WorkspaceNavMenu() {
  const [mounted, setMounted] = useState(false);
  // Something inside More needs attention: the policy rules in force were not
  // the ones last written (a refused edit) or could not be read at all. The
  // dot says "look in here" without opening the menu (Phase 2.6).
  const { rules } = usePolicyRules();
  const attention = rules?.kept_previous === true || rules?.unreadable === true;
  const { open: isSidebarOpen } = useSidebar();
  const { t } = useI18n();

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <>
      <SidebarMenu className="w-full">
        <SidebarMenuItem>
          {mounted ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton
                  size="lg"
                  className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
                >
                  <NavMenuButtonContent
                    isSidebarOpen={isSidebarOpen}
                    t={t}
                    attention={attention}
                  />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
                align="end"
                sideOffset={4}
              >
                <DropdownMenuGroup>
                  <DropdownMenuItem asChild>
                    <Link
                      href="/workspace/settings"
                      data-testid="more-settings"
                    >
                      <Settings2Icon />
                      {t.common.settings}
                      {attention && (
                        <span
                          className="bg-destructive ml-auto size-1.5 rounded-full"
                          aria-label="needs attention"
                        />
                      )}
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <a
                    href="https://omniharness.tech/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <DropdownMenuItem>
                      <GlobeIcon />
                      {t.workspace.officialWebsite}
                    </DropdownMenuItem>
                  </a>
                  <a
                    href="https://github.com/archimedes-run/omniHarness"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <DropdownMenuItem>
                      <GithubIcon />
                      {t.workspace.visitGithub}
                    </DropdownMenuItem>
                  </a>
                  <DropdownMenuSeparator />
                  <a
                    href="https://github.com/archimedes-run/omniHarness/issues"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <DropdownMenuItem>
                      <BugIcon />
                      {t.workspace.reportIssue}
                    </DropdownMenuItem>
                  </a>
                  <a href="mailto:support@omniharness.tech">
                    <DropdownMenuItem>
                      <MailIcon />
                      {t.workspace.contactUs}
                    </DropdownMenuItem>
                  </a>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                  <Link href="/workspace/settings/about">
                    <InfoIcon />
                    {t.workspace.about}
                  </Link>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <SidebarMenuButton size="lg" className="pointer-events-none">
              <NavMenuButtonContent
                isSidebarOpen={isSidebarOpen}
                t={t}
                attention={attention}
              />
            </SidebarMenuButton>
          )}
        </SidebarMenuItem>
      </SidebarMenu>
    </>
  );
}
