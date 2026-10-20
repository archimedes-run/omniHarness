"use client";

import { useCallback } from "react";

import { usePromptInputController } from "@/components/ai-elements/prompt-input";

/**
 * The new-chat starters under the bar (Chat-Bar-v2.dc.html). Each fills the
 * message box and puts the caret at its end; nothing is sent until the user
 * sends it.
 */
export const STARTERS: { label: string; prompt: string }[] = [
  {
    label: "Plan my week",
    prompt:
      "Plan my week: look at my calendar and open tasks, and suggest what to do each day.",
  },
  {
    label: "What's blocked?",
    prompt:
      "What's blocked right now? Check my projects, tasks and coding sessions.",
  },
  {
    label: "Review a coding session",
    prompt:
      "Review my most recent coding session: what it did, what is unfinished, and what needs me.",
  },
  {
    label: "New automation",
    prompt: "Help me set up a new automation: ",
  },
];

export function WelcomeSuggestions() {
  const { textInput } = usePromptInputController();
  const fill = useCallback(
    (prompt: string) => {
      textInput.setInput(prompt);
      requestAnimationFrame(() => {
        const box = document.querySelector<HTMLTextAreaElement>(
          "textarea[name='message']",
        );
        if (!box) return;
        box.focus();
        box.setSelectionRange(prompt.length, prompt.length);
      });
    },
    [textInput],
  );
  return (
    <div className="flex flex-wrap justify-center gap-2" data-testid="starters">
      {STARTERS.map((s) => (
        <button
          key={s.label}
          type="button"
          onClick={() => fill(s.prompt)}
          className="border-border text-foreground-2 hover:bg-surface-raised hover:text-foreground focus-visible:ring-ring h-[34px] rounded-[17px] border px-3.5 text-sm outline-none focus-visible:ring-2 max-sm:h-11"
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}
