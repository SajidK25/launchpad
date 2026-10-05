// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useNotificationInbox } from "./useNotifications";

describe("notification inbox", () => {
  it("loads persisted count and invalidates on live hints and reconnect", async () => {
    const handlers: Array<() => void> = [];
    const client = {
      fetchInbox: vi.fn().mockResolvedValue({
        items: [],
        unreadCount: 3,
        nextCursor: null,
      }),
      markRead: vi.fn(),
      subscribeToChanges: vi.fn((onChange: () => void) => {
        handlers.push(onChange);
        return () => undefined;
      }),
    };
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () => useNotificationInbox(client, { account_id: "founder-1", role: "member", suspended: false }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.inbox.data?.unreadCount).toBe(3));
    expect(client.subscribeToChanges).toHaveBeenCalledOnce();
    act(() => handlers[0]?.());
    await waitFor(() => expect(client.fetchInbox).toHaveBeenCalledTimes(2));
  });

  it("marks only the requested item and reconciles from the server", async () => {
    const client = {
      fetchInbox: vi.fn().mockResolvedValue({
        items: [],
        unreadCount: 2,
        nextCursor: null,
      }),
      markRead: vi.fn().mockResolvedValue({ id: "notice-2" }),
      subscribeToChanges: vi.fn(() => () => undefined),
    };
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () => useNotificationInbox(client, { account_id: "founder-1", role: "member", suspended: false }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.inbox.data).toBeDefined());

    await act(async () => result.current.markRead("notice-2"));

    expect(client.markRead).toHaveBeenCalledWith("notice-2");
    await waitFor(() => expect(client.fetchInbox).toHaveBeenCalledTimes(2));
  });

  it("clears the previous account inbox and live connection on session change", async () => {
    const close = vi.fn();
    const client = {
      fetchInbox: vi.fn().mockResolvedValue({ items: [], unreadCount: 0, nextCursor: null }),
      markRead: vi.fn(),
      subscribeToChanges: vi.fn(() => close),
    };
    const queryClient = new QueryClient();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { rerender } = renderHook(
      ({ account }) => useNotificationInbox(client, account ? { account_id: account, role: "member", suspended: false } : null),
      { initialProps: { account: "founder-1" as string | null }, wrapper },
    );
    await waitFor(() => expect(client.fetchInbox).toHaveBeenCalled());
    rerender({ account: null });

    await waitFor(() => expect(close).toHaveBeenCalledOnce());
    expect(
      queryClient
        .getQueryCache()
        .findAll({ queryKey: ["notifications", "founder-1"] }),
    ).toHaveLength(0);
  });
});
