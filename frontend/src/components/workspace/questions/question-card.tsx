"use client";

import { MessageCircleQuestionMarkIcon } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { AnswerError } from "@/core/questions/api";
import { useAnswerQuestion } from "@/core/questions/hooks";
import {
  answeredText,
  headerOf,
  isOpen,
  submitsOnKey,
  textToSend,
  timeLeft,
} from "@/core/questions/logic";
import type {
  AnswerResult,
  QuestionAnswerInput,
  QuestionView,
} from "@/core/questions/types";
import { cn } from "@/lib/utils";

/**
 * THE question card (specs/009-orchestration/question-card.md, QC-09/QC-10):
 * one component for every asker (the lead now; the coding job and the chat
 * builder place it where they live). It does not know askers: the header
 * names the asker the server sent, and answering posts to one route.
 *
 * Question, context and option text are content (a model or a worker wrote
 * them): already through the display sanitiser (core/questions/api), and
 * rendered as plain text only, never Markdown, never auto-linked.
 *
 * Graphite tokens only; the suggested option is marked in TEXT, not colour
 * alone; Tab moves through the options, Enter/Space chooses; the text box
 * submits with Enter (Shift+Enter is a new line); the state change is
 * announced (aria-live).
 */
export function QuestionCard({
  question,
  onAnswered,
  compact = false,
  className,
}: {
  question: QuestionView;
  /** After the server recorded the answer: e.g. join the resume run. */
  onAnswered?: (result: AnswerResult) => void;
  /** Home's waiting list: the same card, tighter. */
  compact?: boolean;
  className?: string;
}) {
  const answer = useAnswerQuestion();
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  // The server's record wins once it is back; until then the card shows the
  // answer just sent (so the buttons go away at once).
  const [settled, setSettled] = useState<QuestionView | null>(null);
  const shown =
    settled?.id === question.id && question.state === "open"
      ? settled
      : question;
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    if (shown.state !== "open") return;
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, [shown.state]);
  const textId = useId();
  const open = isOpen(shown, now);
  const busy = answer.isPending;

  function send(input: QuestionAnswerInput) {
    setError("");
    answer.mutate(
      { id: question.id, answer: input },
      {
        onSuccess: (result) => {
          setSettled(result.question);
          setText("");
          onAnswered?.(result);
        },
        onError: (e) => {
          setError(
            e instanceof AnswerError && e.status === 409
              ? `This question is no longer open. ${e.message}`
              : `Your answer was not sent: ${e instanceof Error ? e.message : String(e)}`,
          );
        },
      },
    );
  }

  const toSend = textToSend(text, shown.free_text_max);
  const left = timeLeft(shown, now);
  // Due on the client clock but not yet swept: shown as what it is.
  const state = shown.state === "open" && !open ? "expired" : shown.state;
  const announcement =
    state === "answered"
      ? answeredText(shown)
      : state === "expired"
        ? shown.outcome || "No answer in time."
        : "";

  return (
    <section
      aria-label={headerOf(shown)}
      className={cn(
        "border-border bg-card text-card-foreground flex flex-col gap-3 rounded-xl border",
        compact ? "px-4 py-3" : "px-4 py-3.5",
        className,
      )}
      data-testid="question-card"
      data-question-id={shown.id}
      data-state={state}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-foreground-2 flex items-center gap-1.5 text-[13px] font-semibold">
          <MessageCircleQuestionMarkIcon aria-hidden className="size-3.5" />
          {headerOf(shown)}
        </span>
        {left && (
          <span
            className="text-muted-foreground text-xs"
            data-testid="question-time-left"
          >
            {left}
          </span>
        )}
      </div>

      {shown.context && (
        <p
          className="text-muted-foreground text-sm whitespace-pre-line"
          data-testid="question-context"
        >
          {shown.context}
        </p>
      )}
      <p
        className="text-foreground text-[15px] leading-relaxed whitespace-pre-line"
        data-testid="question-text"
      >
        {shown.question}
      </p>

      {state === "open" && (
        <>
          <div
            role="group"
            aria-label="Options"
            className="flex flex-wrap gap-2 max-sm:flex-col"
            data-testid="question-options"
          >
            {shown.options.map((option, index) => {
              const suggested = shown.recommended === index;
              return (
                <Button
                  key={`${shown.id}-${index}`}
                  type="button"
                  variant={suggested ? "default" : "outline"}
                  className="h-auto min-h-9 flex-col items-start gap-0.5 px-3 py-2 text-left whitespace-normal max-md:min-h-11 max-sm:w-full"
                  disabled={busy}
                  onClick={() => send({ option: index })}
                  data-testid="question-option"
                  data-suggested={suggested}
                  aria-describedby={
                    suggested ? `${textId}-suggested` : undefined
                  }
                >
                  <span className="font-medium">{option.label}</span>
                  {suggested && shown.recommended_label && (
                    <span
                      id={`${textId}-suggested`}
                      className="text-xs font-normal"
                      data-testid="question-suggested"
                    >
                      {shown.recommended_label}
                    </span>
                  )}
                  {option.description && (
                    <span className="text-xs font-normal opacity-90">
                      {option.description}
                    </span>
                  )}
                </Button>
              );
            })}
          </div>
          <form
            className="flex items-end gap-2 max-sm:flex-col max-sm:items-stretch"
            onSubmit={(event) => {
              event.preventDefault();
              if (toSend) send({ text: toSend });
            }}
          >
            <label htmlFor={textId} className="sr-only">
              Or answer in your own words
            </label>
            <Textarea
              id={textId}
              value={text}
              rows={1}
              maxLength={shown.free_text_max}
              placeholder="Or answer in your own words"
              className="min-h-9 text-sm"
              disabled={busy}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (submitsOnKey(event)) {
                  event.preventDefault();
                  if (toSend) send({ text: toSend });
                }
              }}
              data-testid="question-text-input"
            />
            <Button
              type="submit"
              variant="secondary"
              className="max-md:min-h-11"
              disabled={busy || !toSend}
              data-testid="question-send"
            >
              Send
            </Button>
          </form>
        </>
      )}

      {state === "answered" && (
        <div
          className="border-border bg-muted rounded-md border px-3 py-2 text-sm"
          data-testid="question-outcome"
        >
          <p>{answeredText(shown)}</p>
          {shown.answer?.text && (
            <p className="text-foreground-2 mt-1 whitespace-pre-line">
              {shown.answer.text}
            </p>
          )}
        </div>
      )}
      {state === "expired" && (
        <p
          className="border-border bg-muted text-foreground-2 rounded-md border px-3 py-2 text-sm"
          data-testid="question-outcome"
        >
          {shown.outcome || "No answer in time; stopped this path."}
        </p>
      )}

      {error && (
        <p className="text-destructive text-sm" role="alert">
          {error}
        </p>
      )}
      <p className="sr-only" aria-live="polite" data-testid="question-live">
        {announcement}
      </p>
    </section>
  );
}
