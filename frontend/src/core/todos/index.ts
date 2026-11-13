import type { Todo } from "./types";

export * from "./types";

const DONE_WHEN = /^\s*done when\s*[:\-–—]\s*/i;

/**
 * The turn's done-criteria (spec 009 FR-051): the checklist's first item when
 * it reads "Done when: …". Returned without its prefix; the remaining items
 * are the steps.
 */
export function splitDoneCriteria(todos: Todo[]): {
  criteria: string | null;
  steps: Todo[];
} {
  const first = todos[0];
  if (first?.content && DONE_WHEN.test(first.content)) {
    return {
      criteria: first.content.replace(DONE_WHEN, "").trim() || null,
      steps: todos.slice(1),
    };
  }
  return { criteria: null, steps: todos };
}

export function todoProgress(todos: Todo[]): {
  done: number;
  total: number;
  current: Todo | null;
} {
  return {
    done: todos.filter((t) => t.status === "completed").length,
    total: todos.length,
    current: todos.find((t) => t.status === "in_progress") ?? null,
  };
}
