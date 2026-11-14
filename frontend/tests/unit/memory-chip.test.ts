import { createElement, isValidElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  MEMORY_TOGGLE_LABEL,
  MemoryOffChipView,
  MemoryToggleView,
} from "@/components/workspace/chat-bar/memory-chip";
import { chatMemoryKey } from "@/core/threads/memory";

/**
 * "Memory off in this chat": the chip above the chat bar (× turns memory back
 * on) and the composer toggle "Don't use memory in this chat". Per chat.
 */
const text = (html: string) => html.replace(/<[^>]+>/g, "");

function find(
  node: unknown,
  pred: (el: ReactElement<Record<string, unknown>>) => boolean,
): ReactElement<Record<string, unknown>> | null {
  if (Array.isArray(node)) {
    for (const n of node) {
      const hit = find(n, pred);
      if (hit) return hit;
    }
    return null;
  }
  if (!isValidElement(node)) return null;
  const el = node as ReactElement<Record<string, unknown>>;
  if (pred(el)) return el;
  return find(el.props.children, pred);
}

describe("the Memory off chip", () => {
  it("says memory is off, as a status, with a named way back", () => {
    const html = renderToStaticMarkup(
      createElement(MemoryOffChipView, { onTurnOn: () => undefined }),
    );
    expect(html).toContain('role="status"');
    expect(text(html)).toContain("Memory off in this chat");
    expect(html).toMatch(
      /<button[^>]*type="button"[^>]*aria-label="Turn memory back on"/,
    );
  });

  it("turns memory back on when × is clicked", () => {
    const onTurnOn = vi.fn();
    const tree = MemoryOffChipView({ onTurnOn });
    const button = find(tree, (el) => el.type === "button");
    (button!.props.onClick as () => void)();
    expect(onTurnOn).toHaveBeenCalledTimes(1);
  });
});

describe("the composer's memory toggle", () => {
  it("is a toggle button labelled for what it does", () => {
    const html = renderToStaticMarkup(
      createElement(MemoryToggleView, {
        memoryOff: false,
        onToggle: () => undefined,
      }),
    );
    expect(html).toContain(
      `aria-label="${MEMORY_TOGGLE_LABEL.replace("'", "&#x27;")}"`,
    );
    expect(MEMORY_TOGGLE_LABEL).toBe("Don't use memory in this chat");
    expect(html).toContain('aria-pressed="false"');
    expect(html).toContain('type="button"');
  });

  it("flips the chat's switch", () => {
    const onToggle = vi.fn();
    const off = MemoryToggleView({ memoryOff: false, onToggle });
    (off.props.onClick as (e: unknown) => void)({});
    expect(onToggle).toHaveBeenLastCalledWith(true);
    const on = MemoryToggleView({ memoryOff: true, onToggle });
    expect(on.props["aria-pressed"]).toBe(true);
    (on.props.onClick as (e: unknown) => void)({});
    expect(onToggle).toHaveBeenLastCalledWith(false);
  });

  it("keeps the state per chat", () => {
    expect(chatMemoryKey("a")).not.toEqual(chatMemoryKey("b"));
    expect(chatMemoryKey("a")).toContain("a");
  });
});
