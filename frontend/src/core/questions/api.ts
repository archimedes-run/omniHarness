import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { safeField, safeLines } from "@/core/display/safe";

import type { AnswerResult, QuestionAnswerInput, QuestionView } from "./types";

/** Question text and options are content (a model or worker wrote them): the
 *  backend sanitises them and they are sanitised again here, once, for every
 *  card that shows them (core/display/safe). */
export function safeQuestion(q: QuestionView): QuestionView {
  return {
    ...q,
    question: safeLines(q.question),
    context: safeLines(q.context),
    options: q.options.map((o) => ({
      label: safeField(o.label),
      description: safeField(o.description),
    })),
    asker: { ...q.asker, name: safeField(q.asker.name) },
    recommended_label:
      q.recommended_label == null ? null : safeField(q.recommended_label),
    answer: q.answer
      ? {
          ...q.answer,
          text: q.answer.text == null ? null : safeLines(q.answer.text),
        }
      : null,
    outcome: safeField(q.outcome),
  };
}

async function readList(url: string): Promise<QuestionView[]> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const body = (await response.json()) as { questions?: QuestionView[] };
  return (body.questions ?? []).map(safeQuestion);
}

export const loadThreadQuestions = (threadId: string) =>
  readList(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/questions`,
  );

export const loadOpenQuestions = () =>
  readList(`${getBackendBaseURL()}/api/questions?state=open`);

export class AnswerError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function answerQuestion(
  id: string,
  answer: QuestionAnswerInput,
): Promise<AnswerResult> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/questions/${encodeURIComponent(id)}/answer`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(answer),
    },
  );
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    const detail =
      typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`;
    throw new AnswerError(response.status, detail);
  }
  const result = (await response.json()) as AnswerResult;
  return { ...result, question: safeQuestion(result.question) };
}
