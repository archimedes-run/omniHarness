"use client";

import {
  BotIcon,
  BoxIcon,
  CodeIcon,
  GitBranchIcon,
  MessagesSquare,
  PlugIcon,
  ShieldQuestionIcon,
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
import { usePendingConfirmations } from "@/core/confirmations/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { useToolSources } from "@/core/tool-sources/hooks";

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  const { pending } = usePendingConfirmations();
  // Only a real count. An unreadable pending set must not render as "0
  // waiting" — that is the same collapse the surface itself refuses to make.
  const waiting = pending?.readable ? pending.actions.length : null;
  // FR-041: a source that failed to load reaches the user here, rather than
  // waiting for them to open the page.
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
            isActive={pathname.startsWith("/workspace/agents")}
            asChild
          >
            <Link className="text-inherit" href="/workspace/agents">
              <BotIcon />
              <span>{t.sidebar.agents}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/mcp")}
            asChild
          >
            <Link className="text-inherit" href="/workspace/mcp">
              <BoxIcon />
              <span>{t.sidebar.mcpSuite}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/confirmations")}
            asChild
          >
            <Link className="text-inherit" href="/workspace/confirmations">
              <ShieldQuestionIcon />
              <span>{t.sidebar.confirmations}</span>
            </Link>
          </SidebarMenuButton>
          {/* The count is the point. Not knowing something was waiting is what
              made a stuck action cost an interruption rather than a click. */}
          {waiting !== null && waiting > 0 && (
            <SidebarMenuBadge data-testid="pending-count">
              {waiting}
            </SidebarMenuBadge>
          )}
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/triggers")}
            asChild
          >
            <Link className="text-inherit" href="/workspace/triggers">
              <ZapIcon />
              <span>{t.sidebar.triggers}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/sessions")}
            asChild
          >
            <Link className="text-inherit" href="/workspace/sessions">
              <CodeIcon />
              <span>{t.sidebar.sessions}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/tool-sources")}
            asChild
          >
            <Link className="text-inherit" href="/workspace/tool-sources">
              <PlugIcon />
              <span>{t.sidebar.toolSources}</span>
            </Link>
          </SidebarMenuButton>
          {failing > 0 && (
            <SidebarMenuBadge data-testid="failing-sources">
              {failing}
            </SidebarMenuBadge>
          )}
        </SidebarMenuItem>
        {process.env.NEXT_PUBLIC_FEATURE_WORKFLOWS === "true" && (
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={pathname.startsWith("/workspace/workflows")}
              asChild
            >
              <Link className="text-inherit" href="/workspace/workflows">
                <GitBranchIcon />
                <span>Workflows</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}
      </SidebarMenu>
    </SidebarGroup>
  );
}
