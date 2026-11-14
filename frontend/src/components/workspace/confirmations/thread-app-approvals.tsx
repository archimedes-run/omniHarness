"use client";

import { useThreadApprovals } from "@/core/apps/hooks";

import { AppApprovalCard } from "./app-approval-card";

/**
 * Spec 011 US1: App access cards raised in this conversation, newest first,
 * resolved ones too (so a card keeps saying "Allowed"). Nothing renders when
 * there are none or the gateway cannot be read: the card is not a chat
 * message and there is no other way to approve from here.
 */
export function ThreadAppApprovals({ threadId }: { threadId: string }) {
  const { data } = useThreadApprovals(threadId);
  if (!data || data.length === 0) return null;
  return (
    <div
      className="flex w-full flex-col gap-3"
      data-testid="thread-app-approvals"
    >
      {data.map((card) => (
        <AppApprovalCard key={card.id} card={card} reveal />
      ))}
    </div>
  );
}
