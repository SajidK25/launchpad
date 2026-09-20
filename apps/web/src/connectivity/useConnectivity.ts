import { useQuery } from "@tanstack/react-query";

import { fetchReadiness, type Fetcher } from "./client";

export type ConnectivityState = "loading" | "connected" | "unavailable";

export function useConnectivity(fetcher?: Fetcher): {
  refresh: () => Promise<unknown>;
  state: ConnectivityState;
} {
  const query = useQuery({
    queryKey: ["connectivity"],
    queryFn: () => fetchReadiness(fetcher),
    refetchOnWindowFocus: false,
    retry: false,
  });

  if (query.isError) {
    return { refresh: query.refetch, state: "unavailable" };
  }
  if (query.isSuccess) {
    return { refresh: query.refetch, state: "connected" };
  }
  return { refresh: query.refetch, state: "loading" };
}
