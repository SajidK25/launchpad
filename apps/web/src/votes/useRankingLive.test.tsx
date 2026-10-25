/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useRankingLive, type RankingLiveClient } from "./useRankingLive";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function createSocket() {
  return {
    onopen: null as ((event: Event) => void) | null,
    onmessage: null as ((event: MessageEvent) => void) | null,
    onclose: null as ((event: CloseEvent) => void) | null,
    onerror: null as ((event: Event) => void) | null,
    close: vi.fn(),
    open() {
      this.onopen?.(new Event("open"));
    },
    message(data: string) {
      this.onmessage?.({ data } as MessageEvent);
    },
    closeConnection() {
      this.onclose?.({} as CloseEvent);
    },
  };
}

function renderLive(
  client: RankingLiveClient,
  queryClient: QueryClient,
  options: { date?: string; enabled?: boolean } = {},
) {
  function Harness() {
    useRankingLive({
      client,
      date: options.date,
      enabled: options.enabled ?? true,
    });
    return null;
  }
  return render(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>,
  );
}

function createQueryClient() {
  const client = new QueryClient();
  vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  return client;
}

describe("useRankingLive", () => {
  it("invalidates API ranking queries from valid current-day hints only", async () => {
    const socket = createSocket();
    const client: RankingLiveClient = {
      issueTicket: vi.fn().mockResolvedValue("short-lived-ticket"),
      connect: vi.fn().mockReturnValue(socket),
    };
    const queryClient = createQueryClient();
    renderLive(client, queryClient);

    await act(async () => {
      await Promise.resolve();
    });
    expect(client.issueTicket).toHaveBeenCalledOnce();
    expect(client.connect).toHaveBeenCalledWith("short-lived-ticket");

    act(() => socket.open());
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["launches", "daily-ranking", "today"],
    });
    vi.mocked(queryClient.invalidateQueries).mockClear();

    act(() =>
      socket.message('{"type":"ranking.invalidated","date":"2026-10-25"}'),
    );
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["launches", "daily-ranking", "2026-10-25"],
    });
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["launches", "daily-ranking", "today"],
    });
    vi.mocked(queryClient.invalidateQueries).mockClear();

    act(() => socket.message('{"type":"vote","voters":["private"]}'));
    act(() => socket.message("not-json"));
    expect(queryClient.invalidateQueries).not.toHaveBeenCalled();
  });

  it("reconnects with a new ticket and reconciles on reconnect and tab focus", async () => {
    const first = createSocket();
    const second = createSocket();
    const client: RankingLiveClient = {
      issueTicket: vi
        .fn()
        .mockResolvedValueOnce("ticket-1")
        .mockResolvedValue("ticket-2"),
      connect: vi.fn().mockReturnValueOnce(first).mockReturnValue(second),
    };
    const queryClient = createQueryClient();
    renderLive(client, queryClient, { date: "2026-10-25" });

    await act(async () => {
      await Promise.resolve();
    });
    act(() => first.closeConnection());
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1_100));
      await Promise.resolve();
    });
    expect(client.issueTicket).toHaveBeenCalledTimes(2);
    expect(client.connect).toHaveBeenLastCalledWith("ticket-2");

    vi.mocked(queryClient.invalidateQueries).mockClear();
    act(() => second.open());
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["launches", "daily-ranking", "2026-10-25"],
    });
    vi.mocked(queryClient.invalidateQueries).mockClear();

    act(() => window.dispatchEvent(new Event("focus")));
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["launches", "daily-ranking", "2026-10-25"],
    });
  });

  it("does not poll or renew a ticket while the socket remains connected", async () => {
    vi.useFakeTimers();
    const socket = createSocket();
    const client: RankingLiveClient = {
      issueTicket: vi.fn().mockResolvedValue("ticket-1"),
      connect: vi.fn().mockReturnValue(socket),
    };
    const queryClient = createQueryClient();
    renderLive(client, queryClient);

    await act(async () => {
      await Promise.resolve();
    });
    act(() => socket.open());
    vi.mocked(queryClient.invalidateQueries).mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(client.issueTicket).toHaveBeenCalledOnce();
    expect(client.connect).toHaveBeenCalledOnce();
    expect(queryClient.invalidateQueries).not.toHaveBeenCalled();
  });
});
