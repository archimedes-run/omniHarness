import type { Message } from "@langchain/langgraph-sdk";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/core/questions/hooks", () => ({
  useAnswerQuestion: () => ({ mutate: () => undefined, isPending: false }),
}));

import { QuestionCard } from "@/components/workspace/questions/question-card";
import { getMessageGroups, isNotAskedMessage } from "@/core/messages/utils";
import type { QuestionView } from "@/core/questions/types";

/**
 * Spec 010 live fixes. A refused ask_clarification ("Not asked: ...") is an
 * instruction to the model: it never becomes a visible question block. An
 * answered question card says what the person chose once, not twice.
 */
const ai = (id: string, callId: string): Message =>
  ({
    id,
    type: "ai",
    content: "",
    tool_calls: [
      {
        id: callId,
        name: "ask_clarification",
        args: { question: "What should it do?" },
      },
    ],
  }) as unknown as Message;
const tool = (
  id: string,
  callId: string,
  content: string,
  kwargs: Record<string, unknown> = {},
): Message =>
  ({
    id,
    type: "tool",
    name: "ask_clarification",
    tool_call_id: callId,
    content,
    additional_kwargs: kwargs,
  }) as unknown as Message;

describe("refused questions are not shown", () => {
  it("a marked or worded 'Not asked' result gets no clarification block", () => {
    const messages: Message[] = [
      {
        id: "h1",
        type: "human",
        content: "create me an agent",
      } as unknown as Message,
      ai("a1", "q1"),
      tool("t1", "q1", "Not asked: each option must be 1 to 60 characters.", {
        omniharness_not_asked: true,
      }),
      ai("a2", "q2"),
      tool("t2", "q2", "Not asked: work on this task has already started."),
      ai("a3", "q3"),
      tool("t3", "q3", "What should the agent do?", {
        omniharness_question: { id: "qq1" },
      }),
    ];
    const groups = getMessageGroups(messages);
    const blocks = groups.filter((g) => g.type === "assistant:clarification");
    expect(blocks.map((g) => g.messages[0]?.id)).toEqual(["t3"]);
    expect(isNotAskedMessage(messages[2]!)).toBe(true);
    expect(isNotAskedMessage(messages[4]!)).toBe(true);
    expect(isNotAskedMessage(messages[6]!)).toBe(false);
  });
});

describe("an answered card says it once", () => {
  it("renders 'You chose' a single time", () => {
    const question: QuestionView = {
      id: "qq1",
      thread_id: "t1",
      asker: { kind: "lead", name: "OmniHarness", tool_call_id: "q3" },
      origin: "content",
      question: "What should the agent do?",
      context: "",
      options: [
        { label: "Session-Watcher Reporter", description: "" },
        { label: "Calendar Day-Briefer", description: "" },
      ],
      recommended: null,
      recommended_label: "",
      on_expiry: "stop",
      expires_at: "2099-11-14T12:00:00Z",
      created_at: "2026-11-13T12:00:00Z",
      state: "answered",
      expired_reason: "",
      answer: { option: 0, text: null, via: "button" },
      outcome: "Answered: Session-Watcher Reporter",
      free_text_max: 2000,
    } as unknown as QuestionView;
    const html = renderToStaticMarkup(
      createElement(QuestionCard, { question }),
    );
    expect(html.split("You chose Session-Watcher Reporter").length - 1).toBe(1);
  });
});
