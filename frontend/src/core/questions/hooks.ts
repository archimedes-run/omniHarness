import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { answerQuestion, loadOpenQuestions, loadThreadQuestions } from "./api";
import type { QuestionAnswerInput } from "./types";

export const QUESTIONS_KEY = ["questions"];

/** A thread's questions. Polled while one is open, so an answer given
 *  elsewhere (a typed reply, Home, another tab) or an expiry shows without a
 *  reload. */
export function useThreadQuestions(threadId: string | null | undefined) {
  const query = useQuery({
    queryKey: [...QUESTIONS_KEY, "thread", threadId],
    queryFn: () => loadThreadQuestions(threadId!),
    enabled: Boolean(threadId),
    refetchInterval: (q) =>
      q.state.data?.some((x) => x.state === "open") ? 15_000 : false,
  });
  return {
    questions: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}

/** Every open question of the caller (Home's "Waiting on you"). */
export function useOpenQuestions() {
  const query = useQuery({
    queryKey: [...QUESTIONS_KEY, "open"],
    queryFn: loadOpenQuestions,
    refetchInterval: 15_000,
  });
  return {
    questions: query.data,
    isLoading: query.isLoading,
    error: query.error,
  };
}

export function useAnswerQuestion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, answer }: { id: string; answer: QuestionAnswerInput }) =>
      answerQuestion(id, answer),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: QUESTIONS_KEY });
    },
  });
}
