import type { BaseStream } from "@langchain/langgraph-sdk";
import { useEffect } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { AgentThreadState } from "@/core/threads";

import { useThreadChat } from "./chats";
import { useShellTitle } from "./shell/shell-context";

export function ThreadTitle({
  thread,
}: {
  className?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
}) {
  const { t } = useI18n();
  const { isNewThread } = useThreadChat();
  useEffect(() => {
    let _title = t.pages.untitled;

    if (thread.values?.title) {
      _title = thread.values.title;
    } else if (isNewThread) {
      _title = t.pages.newChat;
    }
    if (thread.isThreadLoading) {
      document.title = `Loading... - ${t.pages.appName}`;
    } else {
      document.title = `${_title} - ${t.pages.appName}`;
    }
  }, [
    isNewThread,
    t.pages.newChat,
    t.pages.untitled,
    t.pages.appName,
    thread.isThreadLoading,
    thread.values,
  ]);

  // Feature 006: the title is shown in the top bar's left cell.
  useShellTitle(thread.values?.title ?? (isNewThread ? t.pages.newChat : null));
  return null;
}
