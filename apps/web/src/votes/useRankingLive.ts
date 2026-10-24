import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

type RankingInvalidation = { type: "ranking.invalidated"; date: string };

interface RankingLiveSocket {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  close: () => void;
}

export interface RankingLiveClient {
  issueTicket: () => Promise<string>;
  connect: (ticket: string) => RankingLiveSocket;
}

export function createRankingLiveClient(
  fetcher: typeof fetch = globalThis.fetch.bind(globalThis),
  socketFactory: (url: string) => RankingLiveSocket = (url) =>
    new WebSocket(url),
): RankingLiveClient {
  return {
    issueTicket: async () => {
      const response = await fetcher("/api/v1/votes/live-ticket", {
        method: "POST",
        credentials: "include",
      });
      const value: unknown = await response.json().catch(() => null);
      if (
        !response.ok ||
        typeof value !== "object" ||
        value === null ||
        !("ticket" in value) ||
        typeof value.ticket !== "string" ||
        value.ticket.length === 0
      ) {
        throw new Error("Ranking live connection is unavailable.");
      }
      return value.ticket;
    },
    connect: (ticket) => {
      const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
      return socketFactory(
        `${scheme}//${window.location.host}/api/v1/votes/live?ticket=${encodeURIComponent(ticket)}`,
      );
    },
  };
}

const defaultClient = createRankingLiveClient();

export function useRankingLive({
  date,
  enabled,
  client = defaultClient,
}: {
  /** Omit for the API-authoritative current day; set only for an active date. */
  date?: string;
  enabled: boolean;
  client?: RankingLiveClient;
}) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) return;

    let stopped = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let socket: RankingLiveSocket | null = null;
    let failures = 0;

    const invalidate = (eventDate?: string) => {
      if (date !== undefined && eventDate !== undefined && eventDate !== date)
        return;
      const targetDate = date ?? eventDate;
      if (targetDate === undefined) {
        void queryClient.invalidateQueries({
          queryKey: ["launches", "daily-ranking", "today"],
        });
        return;
      }
      void queryClient.invalidateQueries({
        queryKey: ["launches", "daily-ranking", targetDate],
      });
      if (date === undefined) {
        void queryClient.invalidateQueries({
          queryKey: ["launches", "daily-ranking", "today"],
        });
      }
    };

    const scheduleReconnect = () => {
      if (stopped || reconnectTimer !== null) return;
      failures += 1;
      const delay = Math.min(30_000, 1_000 * 2 ** Math.min(failures - 1, 5));
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        void connect();
      }, delay);
    };

    const connect = async () => {
      if (stopped) return;
      let ticket: string;
      try {
        ticket = await client.issueTicket();
      } catch {
        scheduleReconnect();
        return;
      }
      if (stopped) return;

      try {
        socket = client.connect(ticket);
      } catch {
        scheduleReconnect();
        return;
      }
      socket.onopen = () => {
        failures = 0;
        invalidate(date);
      };
      socket.onmessage = (event) => {
        const message = parseInvalidation(event.data);
        if (message) invalidate(message.date);
      };
      socket.onclose = scheduleReconnect;
      socket.onerror = () => socket?.close();
    };

    const onFocus = () => invalidate(date);
    window.addEventListener("focus", onFocus);
    void connect();

    return () => {
      stopped = true;
      window.removeEventListener("focus", onFocus);
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [client, date, enabled, queryClient]);
}

function parseInvalidation(value: unknown): RankingInvalidation | null {
  if (typeof value !== "string") return null;
  try {
    const message: unknown = JSON.parse(value);
    if (
      typeof message === "object" &&
      message !== null &&
      "type" in message &&
      message.type === "ranking.invalidated" &&
      "date" in message &&
      typeof message.date === "string" &&
      /^\d{4}-\d{2}-\d{2}$/.test(message.date)
    ) {
      return { type: "ranking.invalidated", date: message.date };
    }
  } catch {
    // A live frame is only a hint; GraphQL remains the source of ranking state.
  }
  return null;
}
