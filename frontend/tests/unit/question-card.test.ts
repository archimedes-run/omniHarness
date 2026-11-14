import { describe, expect, it } from "vitest";

import { safeQuestion } from "@/core/questions/api";
import {
  answeredText,
  headerOf,
  isOpen,
  questionIdOf,
  submitsOnKey,
  textToSend,
  timeLeft,
} from "@/core/questions/logic";
import type { QuestionView } from "@/core/questions/types";

const NOW = new Date("2026-11-13T12:00:00Z");

function q(over: Partial<QuestionView> = {}): QuestionView {
  return {
    id: "q1",
    thread_id: "t1",
    asker: { kind: "lead", name: "OmniHarness", tool_call_id: "c1" },
    origin: "content",
    question: "Which city?",
    context: "",
    options: [
      { label: "Philadelphia", description: "" },
      { label: "New York", description: "" },
    ],
    recommended: 0,
    recommended_label: "Suggested by OmniHarness",
    on_expiry: "stop",
    expires_at: "2026-11-14T12:00:00Z",
    created_at: "2026-11-13T12:00:00Z",
    state: "open",
    expired_reason: "",
    answer: null,
    outcome: "",
    free_text_max: 2000,
    ...over,
  };
}

describe("question card logic (009 question-card.md)", () => {
  it("names the asker and the time left", () => {
    expect(headerOf(q())).toBe("OmniHarness asks");
    expect(timeLeft(q(), NOW)).toBe("24h 0m left");
    expect(timeLeft(q({ state: "answered" }), NOW)).toBe("");
  });

  it("is open only while open and before its deadline", () => {
    expect(isOpen(q(), NOW)).toBe(true);
    expect(isOpen(q({ expires_at: "2026-11-13T11:59:00Z" }), NOW)).toBe(false);
    expect(isOpen(q({ state: "expired" }), NOW)).toBe(false);
  });

  it("says what was chosen and how", () => {
    const at = NOW.toISOString();
    expect(
      answeredText(
        q({
          state: "answered",
          answer: { option: 1, text: null, via: "button", at },
        }),
      ),
    ).toBe("You chose New York, on the card.");
    expect(
      answeredText(
        q({
          state: "answered",
          answer: { option: null, text: "Boston", via: "tagged_message", at },
        }),
      ),
    ).toBe("You answered by your message:");
  });

  it("Enter sends, Shift+Enter and composition do not", () => {
    expect(submitsOnKey({ key: "Enter", shiftKey: false })).toBe(true);
    expect(submitsOnKey({ key: "Enter", shiftKey: true })).toBe(false);
    expect(
      submitsOnKey({
        key: "Enter",
        shiftKey: false,
        nativeEvent: { isComposing: true },
      }),
    ).toBe(false);
  });

  it("sends trimmed text within the limit only", () => {
    expect(textToSend("  Boston ", 2000)).toBe("Boston");
    expect(textToSend("   ", 2000)).toBeNull();
    expect(textToSend("x".repeat(11), 10)).toBeNull();
  });

  it("finds the card id on the clarification message", () => {
    expect(
      questionIdOf({
        additional_kwargs: { omniharness_question: { id: "q9" } },
      }),
    ).toBe("q9");
    expect(questionIdOf({ additional_kwargs: {} })).toBeNull();
  });

  it("makes content-written text safe to display", () => {
    const safe = safeQuestion(
      q({
        question: "Pick‮ one at https://evil.example/x",
        options: [
          { label: "evil.example", description: "see www.evil.example" },
          { label: "B", description: "" },
        ],
      }),
    );
    expect(safe.question).toBe("Pick one at hxxps://evil[.]example/x");
    expect(safe.options[0]).toEqual({
      label: "evil[.]example",
      description: "see www[.]evil[.]example",
    });
  });
});
