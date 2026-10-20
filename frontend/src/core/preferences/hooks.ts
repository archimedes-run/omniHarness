import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchPreferences, saveDisplayName } from "./appearance";

const KEY = ["preferences"] as const;

/**
 * The signed-in user's preferences. `displayName` is the effective name (the
 * one rule: chosen name, else the email before "@"), or undefined while it
 * cannot be told (loading, or the gateway did not answer: see `error`).
 */
export function usePreferences() {
  const { data, error, isLoading } = useQuery({
    queryKey: KEY,
    queryFn: fetchPreferences,
  });
  return {
    preferences: data,
    displayName: data?.display_name_effective,
    error,
    isLoading,
  };
}

export function useSaveDisplayName() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: saveDisplayName,
    onSuccess: (saved) => client.setQueryData(KEY, saved),
  });
}
