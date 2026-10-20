import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  applyMemoryCleanup,
  clearMemory,
  createMemoryFact,
  deleteMemoryFact,
  importMemory,
  loadMemory,
  previewMemoryCleanup,
  updateMemoryFact,
  updateMemorySection,
} from "./api";
import type {
  MemoryFactInput,
  MemoryFactPatchInput,
  UserMemory,
} from "./types";

export function useMemory() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["memory"],
    queryFn: () => loadMemory(),
  });
  return { memory: data ?? null, isLoading, error };
}

export function useClearMemory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => clearMemory(),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

export function useDeleteMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (factId: string) => deleteMemoryFact(factId),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

export function useImportMemory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (memory: UserMemory) => importMemory(memory),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

export function useCreateMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: MemoryFactInput) => createMemoryFact(input),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

export function useUpdateMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      factId,
      input,
    }: {
      factId: string;
      input: MemoryFactPatchInput;
    }) => updateMemoryFact(factId, input),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

export function useUpdateMemorySection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      group,
      key,
      summary,
    }: {
      group: string;
      key: string;
      summary: string;
    }) => updateMemorySection(group, key, summary),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

/** A mutation, not a query: a preview calls the model and must be asked for. */
export function useMemoryCleanupPreview() {
  return useMutation({ mutationFn: previewMemoryCleanup });
}

export function useApplyMemoryCleanup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: applyMemoryCleanup,
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}
