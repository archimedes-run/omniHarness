/**
 * The agents in a chat (Feature 006 Phase 2): backend state, not a client
 * guess. GET/POST/DELETE /api/threads/{id}/participants. The lead is always a
 * member; calling another agent in adds it; a user turn that @-mentions a
 * member hands that turn to it (the server decides, from the stored members).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export interface Participant {
  name: string;
  description: string;
  lead: boolean;
}

export interface ParticipantsResponse {
  thread_id: string;
  participants: Participant[];
}

const url = (threadId: string, agent?: string) =>
  `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/participants${
    agent ? `/${encodeURIComponent(agent)}` : ""
  }`;

async function read(response: Response): Promise<ParticipantsResponse> {
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new Error(
      body.detail ??
        `the chat's agents could not be changed (${response.status})`,
    );
  }
  return response.json() as Promise<ParticipantsResponse>;
}

export const participantsKey = (threadId: string) => [
  "threadParticipants",
  threadId,
];

/** The agents in this chat, the lead first. `enabled` false for a chat that
 *  does not exist yet on the server. */
export function useThreadParticipants(threadId: string, enabled = true) {
  const { data, error, isLoading } = useQuery({
    queryKey: participantsKey(threadId),
    queryFn: async () => read(await fetch(url(threadId))),
    enabled: enabled && !!threadId,
  });
  return {
    participants: data?.participants ?? [],
    /** Agents other than the lead. */
    members: (data?.participants ?? []).filter((p) => !p.lead),
    error,
    isLoading,
  };
}

export function useCallInAgent(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (agent: string) =>
      read(
        await fetch(url(threadId), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agent }),
        }),
      ),
    onSuccess: (data) =>
      queryClient.setQueryData(participantsKey(threadId), data),
  });
}

export function useRemoveAgent(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (agent: string) =>
      read(await fetch(url(threadId, agent), { method: "DELETE" })),
    onSuccess: (data) =>
      queryClient.setQueryData(participantsKey(threadId), data),
  });
}
