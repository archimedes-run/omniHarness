"use client";

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
}: {
  threadId: string;
  questionId: string;
  fallbackText: string;
  /** The run the server started for the asker to carry on in. */
  onResumed?: (runId: string) => void;
}) {
  const { questions } = useThreadQuestions(threadId);
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
