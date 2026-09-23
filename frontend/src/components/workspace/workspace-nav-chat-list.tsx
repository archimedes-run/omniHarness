"use client";

import {
  BotIcon,
  BoxIcon,
  GitBranchIcon,
  MessagesSquare,
  ShieldQuestionIcon,
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

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  const { pending } = usePendingConfirmations();
  // Only a real count. An unreadable pending set must not render as "0
  // waiting" — that is the same collapse the surface itself refuses to make.
  const waiting = pending?.readable ? pending.actions.length : null;
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
