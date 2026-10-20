"use client";

import type { ChatStatus } from "ai";
import { useEffect, useRef, useState } from "react";

import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { textOfMessage } from "@/core/threads/utils";

import { useThread } from "../messages/context";

/**
 * Follow-up suggestions after a reply finishes (moved unchanged from the old
 * input box): POST /api/threads/{id}/suggestions with the last six turns,
 * once per assistant message, never while disabled or in a mock thread.
 */
export function useFollowups({
  status,
  disabled,
  threadId,
  modelName,
}: {
  status: ChatStatus;
  disabled?: boolean;
  threadId: string;
  modelName: string | undefined;
}) {
  const { thread, isMock } = useThread();
  const [followups, setFollowups] = useState<string[]>([]);
  const [hidden, setHidden] = useState(false);
  const [loading, setLoading] = useState(false);
  const lastGeneratedForAiIdRef = useRef<string | null>(null);
  const wasStreamingRef = useRef(false);
  const messagesRef = useRef(thread.messages);

  useEffect(() => {
    messagesRef.current = thread.messages;
  }, [thread.messages]);

  useEffect(() => {
    const streaming = status === "streaming";
    const wasStreaming = wasStreamingRef.current;
    wasStreamingRef.current = streaming;
    if (!wasStreaming || streaming) {
      return;
    }
    if (disabled || isMock) {
      return;
    }

    const lastAi = [...messagesRef.current]
      .reverse()
      .find((m) => m.type === "ai");
    const lastAiId = lastAi?.id ?? null;
    if (!lastAiId || lastAiId === lastGeneratedForAiIdRef.current) {
      return;
    }
    lastGeneratedForAiIdRef.current = lastAiId;

    const recent = messagesRef.current
      .filter((m) => m.type === "human" || m.type === "ai")
      .map((m) => {
        const role = m.type === "human" ? "user" : "assistant";
        const content = textOfMessage(m) ?? "";
        return { role, content };
      })
      .filter((m) => m.content.trim().length > 0)
      .slice(-6);

    if (recent.length === 0) {
      return;
    }

    const controller = new AbortController();
    setHidden(false);
    setLoading(true);
    setFollowups([]);

    fetch(`${getBackendBaseURL()}/api/threads/${threadId}/suggestions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: recent,
        n: 3,
        model_name: modelName ?? undefined,
      }),
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          return { suggestions: [] as string[] };
        }
        return (await res.json()) as { suggestions?: string[] };
      })
      .then((data) => {
        const suggestions = (data.suggestions ?? [])
          .map((s) => (typeof s === "string" ? s.trim() : ""))
          .filter((s) => s.length > 0)
          .slice(0, 5);
        setFollowups(suggestions);
      })
      .catch(() => {
        setFollowups([]);
      })
      .finally(() => {
        setLoading(false);
      });

    return () => controller.abort();
  }, [modelName, disabled, isMock, status, threadId]);

  const reset = () => {
    setFollowups([]);
    setHidden(false);
    setLoading(false);
  };

  return { followups, hidden, setHidden, loading, reset };
}
