import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  confirmAction,
  declineAction,
  editAndConfirm,
  loadPending,
} from "./api";

const KEY = ["pendingConfirmations"];

export function usePendingConfirmations() {
  const { data, isLoading, error } = useQuery({
    queryKey: KEY,
    queryFn: () => loadPending(),
    // Short, because an action that expires while displayed must become
    // visibly expired without the user reloading (FR-005). The countdown is
    // client-side; this keeps the LIST honest about what still exists.
    refetchInterval: 15_000,
  });
  return { pending: data, isLoading, error };
}

export function useResolveConfirmation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      confirm,
      typedCount,
    }: {
      id: string;
      confirm: boolean;
      typedCount?: number;
    }) => (confirm ? confirmAction(id, typedCount) : declineAction(id)),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: KEY });
      // A confirmed ledger change shows on Projects at once.
      void queryClient.invalidateQueries({ queryKey: ["ledger"] });
    },
  });
}

export function useEditConfirmation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      args,
      typedCount,
    }: {
      id: string;
      args: Record<string, unknown>;
      typedCount?: number;
    }) => editAndConfirm(id, args, typedCount),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: KEY });
      void queryClient.invalidateQueries({ queryKey: ["ledger"] });
    },
  });
}
