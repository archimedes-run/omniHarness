import type { BaseStream } from "@langchain/langgraph-sdk/react";

import type { AgentThreadState } from "../threads";

import { urlOfArtifact } from "./utils";

export async function loadArtifactContent({
  filepath,
  threadId,
  isMock,
}: {
  filepath: string;
  threadId: string;
  isMock?: boolean;
}) {
  let enhancedFilepath = filepath;
  if (filepath.endsWith(".skill")) {
    enhancedFilepath = filepath + "/SKILL.md";
  }
  const url = urlOfArtifact({ filepath: enhancedFilepath, threadId, isMock });
  const response = await fetch(url);
  if (!response.ok) {
    // An error page is not the file: never show its body as the content.
    throw new Error(`Artifact ${enhancedFilepath}: HTTP ${response.status}`);
  }
  const text = await response.text();
  return { content: text, url };
}

/**
 * The sandbox path a `write-file:` step wrote, when the artifacts route can
 * serve it (`/mnt/user-data/...`); null for anything else.
 */
export function writeFileSandboxPath(urlString: string): string | null {
  try {
    const path = decodeURIComponent(new URL(urlString).pathname);
    return path.startsWith("/mnt/user-data/") && !path.includes("/../")
      ? path
      : null;
  } catch {
    return null;
  }
}

export function loadArtifactContentFromToolCall({
  url: urlString,
  thread,
}: {
  url: string;
  thread: BaseStream<AgentThreadState>;
}) {
  const url = new URL(urlString);
  const toolCallId = url.searchParams.get("tool_call_id");
  const messageId = url.searchParams.get("message_id");
  if (messageId && toolCallId) {
    const message = thread.messages.find((message) => message.id === messageId);
    if (message?.type === "ai" && message.tool_calls) {
      const toolCall = message.tool_calls.find(
        (toolCall) => toolCall.id === toolCallId,
      );
      if (toolCall) {
        const content: unknown = toolCall.args.content;
        return typeof content === "string" ? content : undefined;
      }
    }
  }
}
