import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { createContext, useContext } from "react";

import type { AgentThreadState } from "@/core/threads";

export interface ThreadContextType {
  thread: BaseStream<AgentThreadState>;
  isMock?: boolean;
  /**
   * "Try again" on a reply cut off by a restart: sends the person's message
   * again as a new message in this chat (the composer's path). Without it the
   * notice shows no button.
   */
  retry?: (text: string) => void;
}

export const ThreadContext = createContext<ThreadContextType | undefined>(
  undefined,
);

export function useThread() {
  const context = useContext(ThreadContext);
  if (context === undefined) {
    throw new Error("useThread must be used within a ThreadContext");
  }
  return context;
}

/** The chat's context when there is one (no throw): for optional wiring. */
export function useOptionalThread() {
  return useContext(ThreadContext);
}
