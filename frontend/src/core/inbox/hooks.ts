import { useQuery } from "@tanstack/react-query";

import { usePendingConfirmations } from "../confirmations/hooks";

import { loadInboxAlerts } from "./api";
import type { Alert } from "./types";

export function useInboxAlerts() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["inboxAlerts"],
    queryFn: loadInboxAlerts,
    refetchInterval: 30_000,
  });
  return { alerts: data, isLoading, error };
}

/** Waiting or missed, and not dismissed on Home: what the badge counts. */
export const countsTowardBadge = (a: Alert) =>
  (a.state === "waiting" || a.state === "not-delivered") && !a.dismissed;

/**
 * What the sidebar badge shows: pending confirmations plus alerts that are
 * waiting or were missed, leaving out alerts dismissed on Home (the gateway's
 * waiting_count leaves them out; a dismissal also lowers it in the cache at
 * once, see useDismissAlerts). `null` when either half cannot be read,
 * because a badge of "0" would claim nothing is waiting when we cannot tell
 * (FR-008).
 */
export function useInboxCount(): number | null {
  const { pending } = usePendingConfirmations();
  const { alerts, error } = useInboxAlerts();
  if (!pending?.readable || alerts == null || error != null) return null;
  return pending.actions.length + alerts.waiting_count;
}
