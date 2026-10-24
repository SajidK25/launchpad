import { useEffect } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { IdentityClient } from "../identity/client";
import type { createNotificationClient } from "../notifications/client";
import { notificationKeys } from "../notifications/useNotifications";
import type {
  LaunchBookingInput,
  LaunchClient,
  PublicCatalogPage,
  PublicCatalogTopicOptions,
  PublicLaunchPage,
} from "./client";

export type LaunchSession = Pick<
  Awaited<ReturnType<IdentityClient["currentSession"]>>,
  "account_id" | "role" | "suspended"
>;
export type LiveNotificationClient = Pick<
  ReturnType<typeof createNotificationClient>,
  "subscribeToChanges"
>;

export const launchKeys = {
  bookings: (accountId: string, first?: number, after?: string | null) =>
    ["launches", accountId, "bookings", first, after] as const,
  bookingRoot: (accountId: string) =>
    ["launches", accountId, "bookings"] as const,
  preferences: (accountId: string) =>
    ["launches", accountId, "preferences"] as const,
  publicProduct: (productId: string) =>
    ["launches", "public-product", productId] as const,
  publicLaunches: (date?: string) =>
    ["launches", "public", date ?? "today"] as const,
  publicCatalog: (search?: string, topicIds: readonly string[] = []) =>
    [
      "launches",
      "public-catalog",
      normalizeSearch(search),
      normalizeTopicIds(topicIds),
    ] as const,
  publicCatalogTopics: (query?: string, selectedIds: readonly string[] = []) =>
    [
      "launches",
      "public-catalog-topics",
      normalizeSearch(query),
      normalizeTopicIds(selectedIds),
    ] as const,
};

export function usePublicCatalog(
  client: LaunchClient,
  search?: string,
  topicIds: readonly string[] = [],
  first = 20,
) {
  const normalizedSearch = normalizeSearch(search);
  const normalizedTopicIds = normalizeTopicIds(topicIds);
  return useInfiniteQuery<
    PublicCatalogPage,
    Error,
    { pages: PublicCatalogPage[]; pageParams: Array<string | null> },
    ReturnType<typeof launchKeys.publicCatalog>,
    string | null
  >({
    queryKey: launchKeys.publicCatalog(normalizedSearch, normalizedTopicIds),
    initialPageParam: null,
    queryFn: ({ pageParam, signal }) =>
      client.fetchPublicCatalog(
        {
          search: normalizedSearch || undefined,
          topicIds: normalizedTopicIds,
          first,
          after: pageParam ?? undefined,
        },
        signal,
      ),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}

export function usePublicCatalogTopics(
  client: LaunchClient,
  query?: string,
  selectedIds: readonly string[] = [],
  first = 20,
) {
  const normalizedQuery = normalizeSearch(query);
  const normalizedSelectedIds = normalizeTopicIds(selectedIds);
  return useQuery<PublicCatalogTopicOptions, Error>({
    queryKey: launchKeys.publicCatalogTopics(
      normalizedQuery,
      normalizedSelectedIds,
    ),
    queryFn: ({ signal }) =>
      client.fetchPublicCatalogTopics(
        {
          query: normalizedQuery || undefined,
          selectedIds: normalizedSelectedIds,
          first,
        },
        signal,
      ),
  });
}

export function usePublicLaunches(
  client: LaunchClient,
  selectedDate?: string,
  first = 20,
) {
  const queryClient = useQueryClient();
  const query = useInfiniteQuery<
    PublicLaunchPage,
    Error,
    { pages: PublicLaunchPage[]; pageParams: Array<string | null> },
    ReturnType<typeof launchKeys.publicLaunches>,
    string | null
  >({
    queryKey: launchKeys.publicLaunches(selectedDate),
    initialPageParam: null,
    queryFn: ({ pageParam, signal }) =>
      client.fetchPublicLaunches(
        {
          ...(selectedDate === undefined ? {} : { date: selectedDate }),
          first,
          after: pageParam ?? undefined,
        },
        signal,
      ),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    refetchOnWindowFocus: true,
  });

  useEffect(() => {
    if (selectedDate !== undefined) return;
    const now = new Date();
    const nextUtcMidnight = Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate() + 1,
    );
    const timer = window.setTimeout(
      () => {
        void queryClient.resetQueries({
          queryKey: launchKeys.publicLaunches(),
        });
      },
      Math.max(0, nextUtcMidnight - now.getTime()),
    );
    return () => window.clearTimeout(timer);
  }, [queryClient, selectedDate]);

  return query;
}

export function useLaunchBookings(
  client: LaunchClient,
  session: LaunchSession | null,
  first = 20,
  after?: string | null,
) {
  const eligible = session?.role === "member" && session.suspended === false;
  const accountId = eligible ? session.account_id : "";
  return useQuery({
    queryKey: launchKeys.bookings(accountId, first, after),
    queryFn: () => client.fetchLaunchBookings({ first, after }),
    enabled: eligible,
    staleTime: 0,
  });
}

export function useLaunchPreferences(
  client: LaunchClient,
  session: LaunchSession | null,
) {
  const eligible = session?.role === "member" && session.suspended === false;
  const accountId = eligible ? session.account_id : "";
  return useQuery({
    queryKey: launchKeys.preferences(accountId),
    queryFn: client.fetchLaunchPreferences,
    enabled: eligible,
    staleTime: 0,
  });
}

export function usePublicProduct(client: LaunchClient, productId: string) {
  return useQuery({
    queryKey: launchKeys.publicProduct(productId),
    queryFn: () => client.fetchPublicProduct({ id: productId }),
    enabled: productId.length > 0,
  });
}

export function useBookLaunch(
  client: LaunchClient,
  productId: string,
  accountId: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      payload,
      idempotencyKey,
    }: {
      payload: LaunchBookingInput;
      idempotencyKey: string;
    }) => client.createBooking(productId, payload, idempotencyKey),
    onSettled: () => invalidateBookingState(queryClient, productId, accountId),
  });
}

export function useRescheduleLaunch(
  client: LaunchClient,
  productId: string,
  accountId: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      payload,
      idempotencyKey,
    }: {
      payload: LaunchBookingInput;
      idempotencyKey: string;
    }) => client.rescheduleBooking(productId, payload, idempotencyKey),
    onSettled: () => invalidateBookingState(queryClient, productId, accountId),
  });
}

export function useCancelLaunch(
  client: LaunchClient,
  productId: string,
  accountId: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      expectedVersion,
      idempotencyKey,
    }: {
      expectedVersion: number;
      idempotencyKey: string;
    }) => client.cancelBooking(productId, expectedVersion, idempotencyKey),
    onSettled: () => invalidateBookingState(queryClient, productId, accountId),
  });
}

export function useUpdateLaunchPreferences(
  client: LaunchClient,
  accountId: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: client.updateLaunchPreferences,
    onSettled: () =>
      void queryClient.invalidateQueries({
        queryKey: launchKeys.preferences(accountId),
      }),
  });
}

export function useLaunchLiveInvalidation(
  client: LiveNotificationClient,
  session: LaunchSession | null,
) {
  const queryClient = useQueryClient();
  const eligible = session?.role === "member" && session.suspended === false;
  const accountId = eligible ? session.account_id : "";
  useEffect(() => {
    if (!eligible || !accountId) return;
    const invalidate = () => {
      void queryClient.invalidateQueries({
        queryKey: launchKeys.bookingRoot(accountId),
      });
      void queryClient.invalidateQueries({
        queryKey: launchKeys.preferences(accountId),
      });
      void queryClient.invalidateQueries({
        queryKey: notificationKeys.inbox(accountId),
      });
    };
    const unsubscribe = client.subscribeToChanges(invalidate);
    return () => {
      unsubscribe();
      queryClient.removeQueries({ queryKey: ["launches", accountId] });
    };
  }, [accountId, client, eligible, queryClient]);
}

function invalidateBookingState(
  queryClient: ReturnType<typeof useQueryClient>,
  productId: string,
  accountId: string,
) {
  void queryClient.invalidateQueries({
    queryKey: launchKeys.bookingRoot(accountId),
  });
  void queryClient.invalidateQueries({ queryKey: ["products", "viewer"] });
  void queryClient.invalidateQueries({
    queryKey: ["products", "viewer", productId],
  });
}

function normalizeSearch(search?: string): string {
  return (search ?? "").trim().split(/\s+/).filter(Boolean).join(" ");
}

function normalizeTopicIds(topicIds: readonly string[]): string[] {
  return [...new Set(topicIds)].sort();
}
