/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement } from "react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { LaunchClient } from "./client";
import {
  launchKeys,
  useBookLaunch,
  useLaunchLiveInvalidation,
} from "./useLaunches";
import { notificationKeys } from "../notifications/useNotifications";

describe("launch query hooks", () => {
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
