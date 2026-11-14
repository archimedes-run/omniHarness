import { formatRemaining } from "@/core/confirmations/logic";

import type { QuestionView } from "./types";

/** "OmniHarness asks", "The coding job asks". */
export function headerOf(q: QuestionView): string {
  return `${q.asker.name} asks`;
}

/** The clock: "23h 59m left", or "" once it is no longer open. */
export function timeLeft(q: QuestionView, now: Date): string {
  if (q.state !== "open") return "";
  const left = formatRemaining(q.expires_at, now);
  return left === "expired" ? "" : left;
}

export function isOpen(q: QuestionView, now: Date): boolean {
  return q.state === "open" && new Date(q.expires_at).getTime() > now.getTime();
}

/** What the person did, in words ("You chose New York, on the card"). */
export function answeredText(q: QuestionView): string {
  if (q.state !== "answered" || !q.answer) return "";
  const how =
    q.answer.via === "tagged_message" ? "by your message" : "on the card";
  if (q.answer.option != null) {
    const label = q.options[q.answer.option]?.label ?? "";
    return `You chose ${label}, ${how}.`;
  }
  return `You answered ${how}:`;
}

/** Enter submits; Shift+Enter is a new line (QC-10). */
export function submitsOnKey(event: {
  key: string;
  shiftKey: boolean;
  nativeEvent?: { isComposing?: boolean };
}): boolean {
  return (
    event.key === "Enter" &&
    !event.shiftKey &&
    !(event.nativeEvent?.isComposing ?? false)
  );
}

/** The free-text answer to send, or null when there is none to send. */
export function textToSend(text: string, max: number): string | null {
  const trimmed = text.trim();
  if (!trimmed || trimmed.length > max) return null;
  return trimmed;
}

/** The tool message of an `ask_clarification` call that became a card. */
export function questionIdOf(message: {
  additional_kwargs?: Record<string, unknown>;
}): string | null {
  const marker = message.additional_kwargs?.omniharness_question as
    | { id?: unknown }
    | undefined;
  return typeof marker?.id === "string" && marker.id ? marker.id : null;
}
