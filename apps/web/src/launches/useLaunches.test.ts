/** @vitest-environment jsdom */

import {
  focusManager,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement } from "react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { LaunchClient } from "./client";
import {
  launchKeys,
  useBookLaunch,
  useLaunchLiveInvalidation,
  usePublicLaunches,
} from "./useLaunches";
import { notificationKeys } from "../notifications/useNotifications";

describe("launch query hooks", () => {
  it("loads the next page for the same selected date", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    const client = {
      fetchPublicLaunches: vi
        .fn()
        .mockResolvedValueOnce({
          todayDate: "2026-11-01",
          selectedDate: "2026-10-31",
          items: [{ id: "launch-1", name: "Alpha" }],
          nextCursor: "cursor-2",
        })
        .mockResolvedValueOnce({
          todayDate: "2026-11-01",
          selectedDate: "2026-10-31",
          items: [{ id: "launch-2", name: "Beta" }],
          nextCursor: null,
        }),
    } as unknown as LaunchClient;
    const { result } = renderHook(
      () => usePublicLaunches(client, "2026-10-31"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.data?.pages).toHaveLength(1));
    await act(async () => result.current.fetchNextPage());

    expect(client.fetchPublicLaunches).toHaveBeenNthCalledWith(
      1,
      {
        date: "2026-10-31",
        first: 20,
        after: undefined,
      },
      expect.any(AbortSignal),
    );
    expect(client.fetchPublicLaunches).toHaveBeenNthCalledWith(
      2,
      {
        date: "2026-10-31",
        first: 20,
        after: "cursor-2",
      },
      expect.any(AbortSignal),
    );
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(2));
    expect(result.current.data?.pages.flatMap((page) => page.items)).toEqual([
      { id: "launch-1", name: "Alpha" },
      { id: "launch-2", name: "Beta" },
    ]);
  });

  it("resets today's cursor pages at UTC midnight", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    let midnight: (() => void) | undefined;
    let midnightTimer: number | undefined;
    const originalSetTimeout = window.setTimeout.bind(window);
    const timer = vi
      .spyOn(window, "setTimeout")
      .mockImplementation((handler, timeout, ...args) => {
        if (Number(timeout) > 60 * 60 * 1000) midnight = handler as () => void;
        const timerId = originalSetTimeout(
          handler,
          timeout,
          ...args,
        ) as unknown as ReturnType<typeof window.setTimeout>;
        if (Number(timeout) > 60 * 60 * 1000)
          midnightTimer = timerId as unknown as number;
        return timerId;
      });
    const clearTimer = vi.spyOn(window, "clearTimeout");
    const client = {
      fetchPublicLaunches: vi
        .fn()
        .mockResolvedValueOnce({
          todayDate: "2026-11-01",
          selectedDate: "2026-11-01",
          items: [{ id: "launch-1" }],
          nextCursor: "yesterday-cursor",
        })
        .mockResolvedValueOnce({
          todayDate: "2026-11-01",
          selectedDate: "2026-11-01",
          items: [{ id: "launch-2" }],
          nextCursor: null,
        })
        .mockResolvedValue({
          todayDate: "2026-11-02",
          selectedDate: "2026-11-02",
          items: [],
          nextCursor: null,
        }),
    } as unknown as LaunchClient;

    try {
      const { result, unmount } = renderHook(() => usePublicLaunches(client), {
        wrapper,
      });
      await waitFor(() => expect(result.current.data?.pages).toHaveLength(1));
      await act(async () => result.current.fetchNextPage());
      await waitFor(() => expect(result.current.data?.pages).toHaveLength(2));
      expect(midnight).toBeDefined();

      await act(async () => midnight?.());
      await waitFor(() =>
        expect(client.fetchPublicLaunches).toHaveBeenCalledTimes(3),
      );

      expect(client.fetchPublicLaunches).toHaveBeenLastCalledWith(
        {
          first: 20,
          after: undefined,
        },
        expect.any(AbortSignal),
      );
      await waitFor(() => expect(result.current.data?.pages).toHaveLength(1));
      unmount();
      expect(midnightTimer).toBeDefined();
      expect(clearTimer).toHaveBeenCalledWith(midnightTimer);
    } finally {
      timer.mockRestore();
      clearTimer.mockRestore();
    }
  });

  it("refetches today when the tab regains focus without polling", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    const client = {
      fetchPublicLaunches: vi.fn().mockResolvedValue({
        todayDate: "2026-11-01",
        selectedDate: "2026-11-01",
        items: [],
        nextCursor: null,
      }),
    } as unknown as LaunchClient;
    focusManager.setFocused(false);

    try {
      renderHook(() => usePublicLaunches(client), { wrapper });
      await waitFor(() =>
        expect(client.fetchPublicLaunches).toHaveBeenCalledTimes(1),
      );
      await act(async () => focusManager.setFocused(true));
      await waitFor(() =>
        expect(client.fetchPublicLaunches).toHaveBeenCalledTimes(2),
      );
      const query = queryClient
        .getQueryCache()
        .find({ queryKey: launchKeys.publicLaunches() });
      expect(
        (query?.options as { refetchInterval?: number | boolean } | undefined)
          ?.refetchInterval,
      ).toBeUndefined();
    } finally {
      focusManager.setFocused(undefined);
    }
  });

  it("keeps a successful empty launch page distinct from a request failure", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    const emptyClient = {
      fetchPublicLaunches: vi.fn().mockResolvedValue({
        todayDate: "2026-11-01",
        selectedDate: "2026-11-01",
        items: [],
        nextCursor: null,
      }),
    } as unknown as LaunchClient;
    const empty = renderHook(() => usePublicLaunches(emptyClient), { wrapper });
    await waitFor(() => expect(empty.result.current.isSuccess).toBe(true));
    expect(empty.result.current.data?.pages[0]?.items).toEqual([]);
    empty.unmount();

    const failingQueryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const failingWrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, {
        client: failingQueryClient,
        children,
      });
    const failure = new Error("Launch list unavailable.");
    const failingClient = {
      fetchPublicLaunches: vi.fn().mockRejectedValue(failure),
    } as unknown as LaunchClient;
    const failed = renderHook(() => usePublicLaunches(failingClient), {
      wrapper: failingWrapper,
    });
    await waitFor(() => expect(failed.result.current.isError).toBe(true));
    expect(failed.result.current.error).toBe(failure);
    expect(failed.result.current.data).toBeUndefined();
    expect(failed.result.current.refetch).toBeTypeOf("function");
  });

  it("invalidates owner bookings and product state after a successful booking", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    const client = {
      createBooking: vi.fn().mockResolvedValue({
        product_id: "product-1",
        state: "scheduled",
      }),
    } as unknown as LaunchClient;
    const { result } = renderHook(
      () => useBookLaunch(client, "product-1", "founder-1"),
      { wrapper },
    );

    await act(async () =>
      result.current.mutateAsync({
        payload: { launch_date: "2026-11-01", expected_version: 7 },
        idempotencyKey: "booking-key-1",
      }),
    );

    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: launchKeys.bookingRoot("founder-1"),
      }),
    );
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["products", "viewer"],
    });
    expect(client.createBooking).toHaveBeenCalledWith(
      "product-1",
      { launch_date: "2026-11-01", expected_version: 7 },
      "booking-key-1",
    );
  });

  it("preserves cached bookings and exposes a failed server mutation", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    const cachedPage = {
      items: [{ productId: "product-1", state: "scheduled" }],
    };
    queryClient.setQueryData(
      launchKeys.bookings("founder-1", 20, undefined),
      cachedPage,
    );
    const failure = new Error("Booking conflicts with capacity.");
    const client = {
      createBooking: vi.fn().mockRejectedValue(failure),
    } as unknown as LaunchClient;
    const { result } = renderHook(
      () => useBookLaunch(client, "product-1", "founder-1"),
      { wrapper },
    );

    await act(async () => {
      await expect(
        result.current.mutateAsync({
          payload: { launch_date: "2026-11-01", expected_version: 7 },
          idempotencyKey: "booking-key-1",
        }),
      ).rejects.toBe(failure);
    });

    expect(
      queryClient.getQueryData(launchKeys.bookings("founder-1", 20, undefined)),
    ).toEqual(cachedPage);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: launchKeys.bookingRoot("founder-1"),
    });
    await waitFor(() => expect(result.current.error).toBe(failure));
  });

  it("invalidates launch and inbox queries after a live notification change", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    let notifyChanged: (() => void) | undefined;
    const liveClient = {
      subscribeToChanges: vi.fn((callback: () => void) => {
        notifyChanged = callback;
        return vi.fn();
      }),
    };
    const session = {
      account_id: "founder-1",
      role: "member" as const,
      suspended: false,
    };

    renderHook(() => useLaunchLiveInvalidation(liveClient, session), {
      wrapper,
    });
    expect(liveClient.subscribeToChanges).toHaveBeenCalledOnce();
    await act(async () => notifyChanged?.());

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: launchKeys.bookingRoot("founder-1"),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: launchKeys.preferences("founder-1"),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: notificationKeys.inbox("founder-1"),
    });
  });
});
