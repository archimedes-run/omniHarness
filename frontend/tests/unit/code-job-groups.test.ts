import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "vitest";

import { getMessageGroups } from "@/core/messages/utils";

const human = { type: "human", id: "h1", content: "build it" } as Message;
const tool = (id: string, name: string, content: string) =>
  ({ type: "tool", id: `t-${id}`, name, tool_call_id: id, content }) as Message;
const ai = (calls: { id: string; name: string }[]) =>
  ({
    type: "ai",
    id: "a1",
    content: "",
    tool_calls: calls.map((c) => ({ ...c, args: {} })),
  }) as unknown as Message;

describe("coding job groups", () => {
  it("a message with only coding jobs is one card", () => {
    const groups = getMessageGroups([
      human,
      ai([{ id: "cj1", name: "code_job" }]),
      tool("cj1", "code_job", "STATUS VERIFIED"),
    ]);
    expect(groups.map((g) => g.type)).toEqual(["human", "assistant:code-job"]);
  });

  it("other tool calls in the same message keep their own group and results", () => {
    const groups = getMessageGroups([
      human,
      ai([
        { id: "cj1", name: "code_job" },
        { id: "s1", name: "task" },
      ]),
      tool("cj1", "code_job", "STATUS VERIFIED"),
      tool("s1", "task", "Task Succeeded. Result: done"),
    ]);
    expect(groups.map((g) => g.type)).toEqual([
      "human",
      "assistant:code-job",
      "assistant:subagent",
    ]);
    const subagent = groups[2]!;
    expect(
      subagent.messages.some(
        (m) => m.type === "tool" && m.tool_call_id === "s1",
      ),
    ).toBe(true);
  });

  it("a coding job beside an ordinary tool call keeps that call's step", () => {
    const groups = getMessageGroups([
      human,
      ai([
        { id: "cj1", name: "code_job" },
        { id: "w1", name: "web_fetch" },
      ]),
      tool("w1", "web_fetch", "page"),
    ]);
    expect(groups.map((g) => g.type)).toEqual([
      "human",
      "assistant:code-job",
      "assistant:processing",
    ]);
  });
});
