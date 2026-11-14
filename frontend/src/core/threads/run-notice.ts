import type { Message } from "@langchain/langgraph-sdk";

/**
 * A notice the server put into the chat about a run, not a reply from the
 * assistant. Today one kind: the gateway restarted mid-reply, and the reply
 * was cut off (`additional_kwargs.omniharness_run_notice`). The chat shows it
 * as a system notice with a "Try again" that resends the person's message.
 */
export const RUN_NOTICE_MARKER = "omniharness_run_notice";

export interface RunNotice {
  kind: "interrupted";
  reason: string;
  runId: string;
  /**
   * The owner's own message, to send again; null when the cut-off turn was
   * not theirs (relayed channel text, an automation's prompt) or is unknown.
   */
  retryText: string | null;
  /** The message carried files: "Try again" re-sends the text only. */
  hadAttachments: boolean;
  /** The run was a scheduled/automation run. */
  automation: boolean;
}

export function runNotice(
  message: Pick<Message, "type" | "additional_kwargs"> | null | undefined,
): RunNotice | null {
  if (message?.type !== "ai") return null;
  const marker = message.additional_kwargs?.[RUN_NOTICE_MARKER];
  if (!marker || typeof marker !== "object") return null;
  const { kind, reason, run_id, retry_text, had_attachments, automation } =
    marker as Record<string, unknown>;
  if (kind !== "interrupted") return null;
  return {
    kind,
    reason: typeof reason === "string" ? reason : "",
    runId: typeof run_id === "string" ? run_id : "",
    retryText:
      typeof retry_text === "string" && retry_text.trim() ? retry_text : null,
    hadAttachments: had_attachments === true,
    automation: automation === true,
  };
}
