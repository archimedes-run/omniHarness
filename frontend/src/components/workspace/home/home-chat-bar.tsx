"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import {
  PromptInputProvider,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { InputBox } from "@/components/workspace/input-box";
import { ThreadContext } from "@/components/workspace/messages/context";
import { useThreadSettings } from "@/core/settings";
import { SubtasksProvider } from "@/core/tasks/context";
import { useThreadStream } from "@/core/threads/hooks";
import { uuid } from "@/core/utils/uuid";

/**
 * The chat bar at the bottom of Home (Main board; Chat-Bar-v2: 816 px, always
 * at the bottom). The same InputBox every chat uses. Sending starts a new
 * chat exactly as /workspace/chats/new does (same hook, same submit), then
 * opens it; the chat page reconnects to the run (the submit is resumable),
 * so the message and the reply continue there.
 */
export default function HomeChatBar() {
  return (
    <SubtasksProvider>
      <ArtifactsProvider>
        <PromptInputProvider>
          <Bar />
        </PromptInputProvider>
      </ArtifactsProvider>
    </SubtasksProvider>
  );
}

function Bar() {
  const router = useRouter();
  const [threadId] = useState(() => uuid());
  const [settings, setSettings] = useThreadSettings(threadId);
  const [chosenAgent, setChosenAgent] = useState<string | null>(null);
  const { thread, sendMessage, isUploading } = useThreadStream({
    threadId: undefined,
    context: chosenAgent
      ? { ...settings.context, agent_name: chosenAgent }
      : settings.context,
    onStart: (created) =>
      router.push(
        chosenAgent
          ? `/workspace/agents/${encodeURIComponent(chosenAgent)}/chats/${created}`
          : `/workspace/chats/${created}`,
      ),
  });
  const onSubmit = useCallback(
    (message: PromptInputMessage) => void sendMessage(threadId, message),
    [sendMessage, threadId],
  );
  return (
    <ThreadContext.Provider value={{ thread, isMock: false }}>
      <div data-testid="home-chat-bar">
        <InputBox
          className="bg-background/5 w-full"
          isWelcomeMode={false}
          threadId={threadId}
          status={
            thread.error ? "error" : thread.isLoading ? "streaming" : "ready"
          }
          context={settings.context}
          chosenAgent={chosenAgent}
          onChooseAgent={setChosenAgent}
          disabled={isUploading}
          onContextChange={(context) => setSettings("context", context)}
          onSubmit={onSubmit}
          onStop={() => void thread.stop()}
        />
      </div>
    </ThreadContext.Provider>
  );
}
