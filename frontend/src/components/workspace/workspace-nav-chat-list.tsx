"use client";

import {
  BotIcon,
  InboxIcon,
  MessagesSquare,
  PlugIcon,
  ZapIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { useInboxCount } from "@/core/inbox/hooks";
import { useToolSources } from "@/core/tool-sources/hooks";

/**
 * The sidebar (Phase 2.6): New chat (in the header) · Chats · Inbox ·
 * Automations · Connections · Agents, and More (Settings and the rest) in the
 * footer. Projects and Today arrive with Feature 005. Coding sessions keep
 * their route, off the sidebar.
 */
export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  // Pending confirmations plus alerts waiting or missed. Null when either
  // cannot be read: a "0" would claim nothing is waiting (FR-008).
  const waiting = useInboxCount();
  // FR-041 (Feature 004): a tool source that failed to load reaches the user
  // without opening anything: a count on Connections.
  const { view: sources } = useToolSources();
  const failing = sources?.failing ?? 0;
  return (
    <SidebarGroup className="pt-1">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton isActive={pathname === "/workspace/chats"} asChild>
            <Link className="text-inherit" href="/workspace/chats">
              <MessagesSquare />
              <span>{t.sidebar.chats}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/inbox")}
            asChild
          >
            <Link className="text-inherit" href="/workspace/inbox">
              <InboxIcon />
              <span>{t.sidebar.inbox}</span>
            </Link>
          </SidebarMenuButton>
          {waiting === null ? (
            <SidebarMenuBadge
              data-testid="inbox-badge"
              data-count="unknown"
              title="Cannot tell what is waiting"
            >
              ?
            </SidebarMenuBadge>
          ) : (
            waiting > 0 && (
              <SidebarMenuBadge data-testid="inbox-badge" data-count={waiting}>
                {waiting}
              </SidebarMenuBadge>
            )
          )}
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/automations")}
            asChild
          >
            <Link className="text-inherit" href="/workspace/automations">
              <ZapIcon />
              <span>{t.sidebar.automations}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/connections")}
            asChild
          >
            <Link className="text-inherit" href="/workspace/connections">
              <PlugIcon />
              <span>{t.sidebar.connections}</span>
            </Link>
          </SidebarMenuButton>
          {failing > 0 && (
            <SidebarMenuBadge
              className="text-destructive"
              data-testid="failing-sources"
              title={`${failing} tool source(s) failing`}
            >
              {failing}
            </SidebarMenuBadge>
          )}
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/agents")}
            asChild
          >
            <Link className="text-inherit" href="/workspace/agents">
              <BotIcon />
              <span>{t.sidebar.agents}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarGroup>
  );
}
