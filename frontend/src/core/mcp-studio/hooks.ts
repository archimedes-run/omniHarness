import { useQuery } from "@tanstack/react-query";

import { listBuiltServers } from "./api";

/** Built servers. Polls while one is drafting, building or turning on. */
export function useBuiltServers() {
  const query = useQuery({
    queryKey: ["builtServers"],
    queryFn: listBuiltServers,
    retry: false,
    refetchInterval: (q) =>
      q.state.data?.servers.some(
        (s) =>
          s.state === "drafting" ||
          s.state === "building" ||
          s.state === "turning_on",
      )
        ? 3_000
        : false,
  });
  return {
    servers: query.data?.servers,
    isLoading: query.isLoading,
    error: query.error,
  };
}
