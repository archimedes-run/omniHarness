"use client";

import {
  BugIcon,
  ChevronsUpDown,
  GlobeIcon,
  InfoIcon,
  MailIcon,
  Settings2Icon,
  SettingsIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
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
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { useToolSources } from "@/core/tool-sources/hooks";

import { GithubIcon } from "./github-icon";

function NavMenuButtonContent({
  isSidebarOpen,
  t,
}: {
  isSidebarOpen: boolean;
  t: ReturnType<typeof useI18n>["t"];
}) {
  return isSidebarOpen ? (
    <div className="flex w-full items-center gap-2 text-left text-sm text-inherit">
      <SettingsIcon className="size-4" />
      <span>{t.workspace.settingsAndMore}</span>
      <ChevronsUpDown className="ml-auto size-4 text-current" />
    </div>
  ) : (
    <div className="flex size-full items-center justify-center">
      <SettingsIcon className="size-4 text-current" />
    </div>
  );
}

export function WorkspaceNavMenu() {
  const [mounted, setMounted] = useState(false);
  const pathname = usePathname();
  // FR-041 (Feature 004): a tool source that failed to load reaches the user
  // in the sidebar, without opening its page. Connections live in Settings
  // now, so the count rides on the Settings entry.
  const { view: sources } = useToolSources();
  const failing = sources?.failing ?? 0;
  const { open: isSidebarOpen } = useSidebar();
  const { t } = useI18n();

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <>
      <SidebarMenu className="w-full">
        {/* Settings is a page now (Phase 2.5): Connections, Safety and the
            Activity log live there alongside the old dialog's sections. */}
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/settings")}
            asChild
          >
            <Link
              className="text-inherit"
              href={
                failing > 0
                  ? "/workspace/settings/connections"
                  : "/workspace/settings"
              }
            >
              <Settings2Icon />
              <span>{t.sidebar.settings}</span>
            </Link>
          </SidebarMenuButton>
          {failing > 0 && (
            <SidebarMenuBadge
              className="text-destructive"
              data-testid="failing-sources"
              title={`${failing} tool source(s) failing — see Connections`}
            >
              {failing}
            </SidebarMenuBadge>
          )}
        </SidebarMenuItem>
        <SidebarMenuItem>
          {mounted ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton
                  size="lg"
                  className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
                >
                  <NavMenuButtonContent isSidebarOpen={isSidebarOpen} t={t} />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
                align="end"
                sideOffset={4}
              >
                <DropdownMenuGroup>
                  <DropdownMenuItem asChild>
                    <Link href="/workspace/settings/appearance">
                      <Settings2Icon />
                      {t.common.settings}
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
              <NavMenuButtonContent isSidebarOpen={isSidebarOpen} t={t} />
            </SidebarMenuButton>
          )}
        </SidebarMenuItem>
      </SidebarMenu>
    </>
  );
}
