import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { Message } from "@langchain/langgraph-sdk";
import {
  createElement,
  isValidElement,
  type ReactElement,
  type ReactNode,
} from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ThreadContext } from "@/components/workspace/messages/context";
import { MessageListItem } from "@/components/workspace/messages/message-list-item";
import {
  INTERRUPTED_TEXT,
  RunNotice,
  RunNoticeView,
  guardRetry,
} from "@/components/workspace/messages/run-notice";
import { DISCLOSURE_MARKER } from "@/core/disclosure";
import { RUN_NOTICE_MARKER, runNotice } from "@/core/threads/run-notice";

/**
 * A reply cut off by a gateway restart: the server appends an "ai" message
 * marked `omniharness_run_notice`; the chat shows it as a system notice with
 * "Try again" (resends the person's message, on a click only, once).
 */
const noop = () => undefined;
const text = (html: string) => html.replace(/<[^>]+>/g, "");

const DISCLOSED = "\n\nRan without asking: write_file";

function interrupted(retry: string | null, disclosed = false): Message {
  return {
    id: "run-interrupted-r1",
    type: "ai",
    content: INTERRUPTED_TEXT + (disclosed ? DISCLOSED : ""),
    additional_kwargs: {
      [RUN_NOTICE_MARKER]: {
        kind: "interrupted",
        reason: "restart",
        run_id: "r1",
        retry_text: retry,
      },
      ...(disclosed
        ? {
            [DISCLOSURE_MARKER]: {
              text: DISCLOSED,
              items: [{ tool: "write_file", text: "I used write_file." }],
              sources: [],
            },
          }
        : {}),
    },
  };
}

/** The <button> elements a hook-free view returns (its own tree only). */
function buttons(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(buttons);
  if (!isValidElement(node)) return [];
  const el = node as ReactElement<Record<string, unknown>>;
  const own = el.type === "button" ? [el] : [];
  return [...own, ...buttons(el.props.children as ReactNode)];
}

const withThread = (
  child: ReactElement,
  isLoading: boolean,
  retry?: () => void,
) =>
  createElement(
    ThreadContext.Provider,
    {
      value: {
        thread: { isLoading } as never,
        retry,
      },
    },
    child,
  );

describe("runNotice (core)", () => {
  it("reads the interrupted marker and its retry text", () => {
    expect(runNotice(interrupted("Plan my week"))).toEqual({
      kind: "interrupted",
      reason: "restart",
      runId: "r1",
      retryText: "Plan my week",
    });
  });

  it("has no retry text when it is null or blank", () => {
    expect(runNotice(interrupted(null))?.retryText).toBeNull();
    expect(runNotice(interrupted("  "))?.retryText).toBeNull();
  });

  it("is nothing for an ordinary reply, another kind, or a human message", () => {
    expect(runNotice({ type: "ai", additional_kwargs: {} })).toBeNull();
    expect(
      runNotice({
        type: "ai",
        additional_kwargs: { [RUN_NOTICE_MARKER]: { kind: "other" } },
      } as unknown as Message),
    ).toBeNull();
    expect(runNotice({ ...interrupted("x"), type: "human" })).toBeNull();
  });
});

describe("the interrupted notice", () => {
  it("renders as a status with its text and a real Try again button", () => {
    const html = renderToStaticMarkup(
      createElement(RunNoticeView, {
        retryText: "Plan my week",
        onRetry: () => undefined,
      }),
    );
    expect(html).toContain('role="status"');
    expect(text(html)).toContain(INTERRUPTED_TEXT);
    expect(html).toMatch(/<button[^>]*type="button"[^>]*>.*Try again/);
    expect(html).toContain("focus-visible:ring-2");
  });

  it("sends the retry text when Try again is clicked", () => {
    const onRetry = vi.fn();
    const tree = RunNoticeView({ retryText: "Plan my week", onRetry });
    const [button] = buttons(tree);
    (button!.props.onClick as () => void)();
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onRetry).toHaveBeenCalledWith("Plan my week");
  });

  it("sends at most once, and never while a run is under way", () => {
    const retry = vi.fn();
    let sent = false;
    let busy = true;
    const click = guardRetry(
      retry,
      () => sent || busy,
      () => {
        sent = true;
      },
    );
    click("Plan my week");
    expect(retry).not.toHaveBeenCalled();
    busy = false;
    click("Plan my week");
    click("Plan my week");
    expect(retry).toHaveBeenCalledTimes(1);
    expect(retry).toHaveBeenCalledWith("Plan my week");
  });

  it("disables the button while the chat is running", () => {
    const busy = renderToStaticMarkup(
      withThread(createElement(RunNotice, { retryText: "Plan" }), true, noop),
    );
    expect(busy).toMatch(/<button[^>]*disabled=""[^>]*>.*Try again/);
    const idle = renderToStaticMarkup(
      withThread(createElement(RunNotice, { retryText: "Plan" }), false, noop),
    );
    expect(idle).toContain("Try again");
    expect(idle).not.toMatch(/<button[^>]*disabled=""[^>]*>.*Try again/);
  });

  it("has no button without retry text, or without a chat to send to", () => {
    expect(
      renderToStaticMarkup(
        withThread(createElement(RunNotice, { retryText: null }), false, noop),
      ),
    ).not.toContain("Try again");
    expect(
      renderToStaticMarkup(createElement(RunNotice, { retryText: "Plan" })),
    ).not.toContain("Try again");
  });

  it("is what the message list shows for the marked message, with its disclosure", () => {
    const html = renderToStaticMarkup(
      withThread(
        createElement(MessageListItem, {
          message: interrupted("Plan my week", true),
          threadId: "t1",
        }),
        false,
        noop,
      ),
    );
    expect(html).toContain('data-testid="run-notice"');
    expect(text(html)).toContain(INTERRUPTED_TEXT);
    // The disclosure block is the note, not part of the notice's sentence.
    expect(html).toContain('data-testid="disclosure-note"');
    expect(text(html)).toContain("Ran without asking: write_file");
    expect(text(html)).not.toContain(INTERRUPTED_TEXT + "\n\nRan");
    expect(text(html)).toContain("Try again");
  });

  it("uses theme tokens only, and wraps at phone width", () => {
    const source = readFileSync(
      join(
        __dirname,
        "..",
        "..",
        "src",
        "components",
        "workspace",
        "messages",
        "run-notice.tsx",
      ),
      "utf-8",
    );
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,6}\b|rgb\(/);
    expect(source).toContain("flex-wrap");
    expect(source).toContain("break-words");
  });
});
