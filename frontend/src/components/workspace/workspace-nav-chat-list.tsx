"use client";

import { MessageSquarePlus, MessagesSquare, PlugIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { useInboxCount } from "@/core/inbox/hooks";
import { useToolSources } from "@/core/tool-sources/hooks";

/** Sidebar rows are 44 px tall at phone width (touch targets). */
const ROW = "max-md:h-11";

/**
 * The sidebar (Feature 006): New chat · Chats · MCP Suite, then Recent chats;
 * the user and More in the footer. Agents, Skills, Automations and Tasks are
 * the capsule's panels; Inbox became Home (interim: /workspace/home).
 */
export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  // Pending confirmations plus alerts waiting or missed. Null when either
  // cannot be read: a "0" would claim nothing is waiting (FR-008).
  const waiting = useInboxCount();
  // FR-041 (Feature 004): a tool source that failed to load reaches the user
  // without opening anything: a count on MCP Suite.
  // Unreadable is "?", never a quiet zero (FR-008's rule, here too).
  const { view: sources, error: sourcesError } = useToolSources();
  const failing: number | null =
    sourcesError != null ? null : (sources?.failing ?? 0);
  const waitingLabel =
    waiting === null ? t.sidebar.cannotTellWaiting : t.sidebar.waiting(waiting);
  return (
    <SidebarGroup className="pt-1">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            // The Main board marks Home as "New chat": Home is where a new
            // chat starts (its chat bar), with what needs you above it.
            isActive={
              pathname === "/workspace/home" ||
              pathname === "/workspace/chats/new"
            }
            className={ROW}
            asChild
          >
            <Link className="text-inherit" href="/workspace/home">
              <MessageSquarePlus />
              <span>{t.sidebar.newChat}</span>
            </Link>
          </SidebarMenuButton>
          {(waiting === null || waiting > 0) && (
            // What is waiting is listed on Home: the count links there.
            <SidebarMenuAction
              asChild
              className="aspect-auto w-auto min-w-5 after:hidden max-md:top-0 max-md:right-0 max-md:size-11"
            >
              <Link
                href="/workspace/home"
                data-testid="inbox-badge"
                data-count={waiting ?? "unknown"}
                title={waitingLabel}
                aria-label={waitingLabel}
              >
                <span
                  aria-hidden
                  className="bg-warning text-warning-foreground flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-xs font-semibold tabular-nums"
                >
                  {waiting ?? "?"}
                </span>
              </Link>
            </SidebarMenuAction>
          )}
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/chats"}
            className={ROW}
            asChild
          >
            <Link className="text-inherit" href="/workspace/chats">
              <MessagesSquare />
              <span>{t.sidebar.chats}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/connections")}
            className={ROW}
            asChild
          >
            <Link className="text-inherit" href="/workspace/connections">
              <PlugIcon />
              <span>{t.sidebar.mcpSuite}</span>
            </Link>
          </SidebarMenuButton>
          {(failing === null || failing > 0) && (
            // Amber, as on the board: unreachable is a warning, not an error.
            <SidebarMenuBadge
              className="text-warning max-md:top-3"
              data-testid="failing-sources"
              data-count={failing ?? "unknown"}
              role="img"
              aria-label={
                failing === null
                  ? t.sidebar.cannotTellSources
                  : t.sidebar.failingSources(failing)
              }
              title={
                failing === null
                  ? t.sidebar.cannotTellSources
                  : t.sidebar.failingSources(failing)
              }
            >
              {failing ?? "?"}
            </SidebarMenuBadge>
          )}
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarGroup>
  );
}
