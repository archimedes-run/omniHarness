"use client";

import { useCallback, useEffect, useState } from "react";

import type { Alert } from "@/core/inbox/types";

/**
 * Which "While you were away" alerts the user dismissed. The gateway has no
 * alert-acknowledge route, so this is kept in this browser's localStorage:
 * a dismissal does not follow you to another device, and Home says so.
 */
const KEY = "omni-harness.home.dismissed-alerts";

export const alertKey = (a: Pick<Alert, "rule_id" | "event_id">) =>
  `${a.rule_id}:${a.event_id}`;

function read(): string[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter((k): k is string => typeof k === "string")
      : [];
  } catch {
    return [];
  }
}

function write(keys: string[]) {
  try {
    // Bounded: old keys fall off; their alerts have aged out of the 24 h
    // window the gateway reports anyway.
    window.localStorage.setItem(KEY, JSON.stringify(keys.slice(-500)));
  } catch {
    // Storage blocked: the dismissal lasts until reload.
  }
}

export function useDismissedAlerts() {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  useEffect(() => setDismissed(new Set(read())), []);
  const dismiss = useCallback((keys: string[]) => {
    setDismissed((prev) => {
      const next = new Set([...prev, ...keys]);
      write([...next]);
      return next;
    });
  }, []);
  return { dismissed, dismiss };
}
