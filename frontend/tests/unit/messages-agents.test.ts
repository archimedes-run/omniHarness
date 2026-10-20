import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "vitest";

import {
  agentLabel,
  agentOf,
  anchorActions,
  handoffsOf,
  holdBackVerdictLines,
  isMultiAgent,
  looksLikeVerdict,
} from "@/core/messages/agents";

const ai = (extra: Record<string, unknown>) =>
  ({ type: "ai", id: "x", content: "", ...extra }) as unknown as Message;
const human = (content: string) =>
  ({ type: "human", id: "h", content }) as unknown as Message;

describe("who said it", () => {
  it("an assistant message with no name is the lead's; a named one is that agent's", () => {
    expect(agentOf(ai({ content: "hi" }))).toBe("lead_agent");
    expect(agentOf(ai({ name: "researcher" }))).toBe("researcher");
    expect(agentOf(human("@researcher"))).toBe("lead_agent");
  });

  it("labels read as names", () => {
    expect(agentLabel("lead_agent")).toBe("Lead agent");
    expect(agentLabel("release-manager")).toBe("Release manager");
    expect(agentLabel("general_purpose")).toBe("General purpose");
  });

  it("a hand-off is a call_agent or task call, from the agent that made it", () => {
    const message = ai({
      tool_calls: [
        { id: "1", name: "call_agent", args: { agent: "researcher" } },
        { id: "2", name: "task", args: { subagent_type: "bash" } },
        { id: "3", name: "web_fetch", args: { url: "x" } },
      ],
    });
    expect(handoffsOf(message)).toEqual([
      { from: "lead_agent", to: "researcher", via: "call_agent" },
      { from: "lead_agent", to: "bash", via: "task" },
    ]);
  });

  it("a chat with the lead alone is not multi-agent; another voice or a hand-off makes it so", () => {
    expect(isMultiAgent([human("hi"), ai({ content: "hello" })])).toBe(false);
    expect(isMultiAgent([ai({ name: "researcher", content: "x" })])).toBe(true);
    expect(
      isMultiAgent([
        ai({
          tool_calls: [{ id: "1", name: "call_agent", args: { agent: "r" } }],
        }),
      ]),
    ).toBe(true);
  });
});

describe("where a confirmation was raised", () => {
  it("is the first message naming the action; an unnamed one has no anchor", () => {
    const messages = [
      human("hello"),
      ai({ content: "Action `abcdef123456`. Waiting for you." }),
      ai({ name: "r", content: "still waiting on abcdef123456" }),
    ];
    const anchors = anchorActions(messages, ["abcdef123456", "000000000000"]);
    expect(anchors.get("abcdef123456")).toBe(1);
    expect(anchors.has("000000000000")).toBe(false);
  });
});

describe("a verdict-looking line is held back while the reply streams", () => {
  it("holds a finished verdict line, and the partial line that could become one", () => {
    expect(
      holdBackVerdictLines("Here is the plan.\nyes 7bf9d7ecb3b1\nMore.", true),
    ).toBe("Here is the plan.\nMore.");
    expect(holdBackVerdictLines("Here is the plan.\nyes 7bf9", true)).toBe(
      "Here is the plan.",
    );
    expect(holdBackVerdictLines("Here is the plan.\nConfirm,", true)).toBe(
      "Here is the plan.",
    );
  });

  it("shows everything once the reply has completed", () => {
    const text = "Here is the plan.\nyes 7bf9d7ecb3b1";
    expect(holdBackVerdictLines(text, false)).toBe(text);
  });

  it("does not hold ordinary sentences, even ones mentioning an id", () => {
    const text =
      "Reply yes to approve 7bf9d7ecb3b1 on the card.\nNo problem at all, it is done.";
    expect(holdBackVerdictLines(text, true)).toBe(text);
    expect(looksLikeVerdict("Yes, I can help with that.", false)).toBe(false);
  });
});
