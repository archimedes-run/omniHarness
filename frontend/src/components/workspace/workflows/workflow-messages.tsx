"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { useEffect, useState } from "react";

import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { MessageGroup } from "@/components/workspace/messages/message-group";
import { MessageListItem } from "@/components/workspace/messages/message-list-item";
import { getMessageGroups } from "@/core/messages/utils";
import { SubtasksProvider } from "@/core/tasks/context";

import { getRunMessages } from "./api";

interface WorkflowMessagesInnerProps {
  threadId: string;
  runId: string;
  messages: Message[];
}

function WorkflowMessagesInner({
  threadId,
  runId,
  messages,
}: WorkflowMessagesInnerProps) {
  const groups = getMessageGroups(messages);

  if (groups.length === 0) {
    return (
      <p className="text-muted-foreground py-4 text-sm">
        No messages recorded.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {groups.map((group) => {
        if (group.type === "human") {
          return (
            <div key={group.id ?? group.messages[0]?.id}>
              {group.messages.map((msg) => (
                <MessageListItem
                  key={msg.id}
                  message={msg}
                  threadId={threadId}
                  runId={runId}
                />
              ))}
            </div>
          );
        }

        if (group.type === "assistant") {
          return (
            <div key={group.id ?? group.messages[0]?.id}>
              {group.messages.map((msg) => (
                <MessageListItem
                  key={msg.id}
                  message={msg}
                  threadId={threadId}
                  runId={runId}
                />
              ))}
            </div>
          );
        }

        if (group.type === "assistant:clarification") {
          return (
            <div key={group.id ?? group.messages[0]?.id}>
              {group.messages.map((msg) => (
                <MessageListItem
                  key={msg.id}
                  message={msg}
                  threadId={threadId}
                  runId={runId}
                />
              ))}
            </div>
          );
        }

        if (group.type === "assistant:present-files") {
          return (
            <div key={group.id ?? group.messages[0]?.id}>
              {group.messages.map((msg) => (
                <MessageListItem
                  key={msg.id}
                  message={msg}
                  threadId={threadId}
                  runId={runId}
                />
              ))}
            </div>
          );
        }

        // assistant:processing | assistant:subagent | fallback → MessageGroup
        return (
          <MessageGroup
            key={group.id ?? group.messages[0]?.id}
            messages={group.messages}
          />
        );
      })}
    </div>
  );
}

interface WorkflowMessagesProps {
  threadId: string;
  runId: string;
}

export function WorkflowMessages({ threadId, runId }: WorkflowMessagesProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getRunMessages(threadId, runId)
      .then((result) => {
        if (!cancelled) {
          setMessages(
            result.data
              .filter((ev) => !ev.metadata?.caller?.startsWith("middleware:"))
              .map((ev) => ev.content),
          );
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Failed to load messages",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [threadId, runId]);

  return (
    <ArtifactsProvider>
      <SubtasksProvider>
        {loading ? (
          <div className="text-muted-foreground py-4 text-sm">
            Loading messages…
          </div>
        ) : error ? (
          <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-4 py-3 text-sm">
            {error}
          </div>
        ) : (
          <WorkflowMessagesInner
            threadId={threadId}
            runId={runId}
            messages={messages}
          />
        )}
      </SubtasksProvider>
    </ArtifactsProvider>
  );
}
