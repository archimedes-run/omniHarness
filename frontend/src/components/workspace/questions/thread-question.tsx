"use client";

import { useEffect } from "react";

import { safeLines } from "@/core/display/safe";
import { useThreadQuestions } from "@/core/questions/hooks";

import { QuestionCard } from "./question-card";

/**
 * The lead's question, where it asked it (under its reply): the card for
 * the question this `ask_clarification` call opened, read from the thread's
 * questions. Until the record is read (or if it cannot be), the question's
 * own text is shown, as plain text.
 */
export function ThreadQuestion({
  threadId,
  questionId,
  fallbackText,
  onResumed,
  messageCount,
}: {
  threadId: string;
  questionId: string;
  fallbackText: string;
  /** The run the server started for the asker to carry on in. */
  onResumed?: (runId: string) => void;
  /** The thread's message count: a new message (a typed answer, the lead's
   *  reply) reads the card again at once instead of at the next poll. */
  messageCount?: number;
}) {
  const { questions, refetch } = useThreadQuestions(threadId);
  useEffect(() => {
    if (messageCount != null) void refetch();
  }, [messageCount, refetch]);
  const question = questions?.find((q) => q.id === questionId);
  if (!question) {
    return (
      <p
        className="text-foreground text-sm whitespace-pre-line"
        data-testid="question-fallback"
      >
        {safeLines(fallbackText)}
      </p>
    );
  }
  return (
    <QuestionCard
      question={question}
      onAnswered={(result) => {
        if (result.resume_run_id) onResumed?.(result.resume_run_id);
      }}
    />
  );
}
