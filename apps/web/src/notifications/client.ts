import type { components } from "@launchpad/contracts";
import {
  VIEWER_NOTIFICATION_INBOX_QUERY,
  type ViewerNotificationInboxQuery,
  type ViewerNotificationInboxQueryVariables,
} from "@launchpad/contracts/src/graphql.generated";
import type { IdentityClient } from "../identity/client";

type Schemas = components["schemas"];
type Fetcher = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;
export type NotificationKind =
  | "review_approved"
  | "review_rejected"
  | "review_changes_requested";
export type NotificationPage = Omit<
  ViewerNotificationInboxQuery["viewerNotificationInbox"],
  "items"
> & {
  items: Array<
    Omit<ViewerNotificationInboxQuery["viewerNotificationInbox"]["items"][number], "kind"> & {
      kind: NotificationKind;
    }
  >;
};
export type NotificationRead = Schemas["NotificationReadResponse"];

export class NotificationRequestError extends Error {
  constructor(readonly status: number, readonly body: unknown) {
    super(`Notification request failed with status ${status}.`);
  }
}

export function createNotificationClient(
  fetcher: Fetcher = globalThis.fetch.bind(globalThis),
  identity: Pick<IdentityClient, "ensureSession" | "getCsrfToken">,
) {
  return {
    fetchInbox: async (
      variables: ViewerNotificationInboxQueryVariables = {},
    ): Promise<NotificationPage> => {
      await identity.ensureSession();
      const response = await fetcher("/api/v1/graphql", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: VIEWER_NOTIFICATION_INBOX_QUERY,
          variables,
        }),
      });
      const value: unknown = await response.json().catch(() => null);
      if (!response.ok || !isRecord(value))
        throw new NotificationRequestError(response.status, value);
      const result = value as {
        data?: ViewerNotificationInboxQuery;
        errors?: unknown[];
      };
      if (result.errors?.length || !result.data?.viewerNotificationInbox)
        throw new NotificationRequestError(response.status, result.errors ?? value);
      return validateInbox(result.data.viewerNotificationInbox);
    },
    markRead: async (id: string): Promise<NotificationRead> => {
      await identity.ensureSession();
      const headers: Record<string, string> = {};
      const csrf = identity.getCsrfToken();
      if (csrf) headers["X-CSRF-Token"] = csrf;
      const response = await fetcher(
        `/api/v1/me/notifications/${encodeURIComponent(id)}/read`,
        { method: "PUT", credentials: "include", headers },
      );
      const value: unknown = await response.json().catch(() => null);
      if (!response.ok || !isRecord(value))
        throw new NotificationRequestError(response.status, value);
      return value as NotificationRead;
    },
    subscribeToChanges: (onChange: () => void): (() => void) => {
      let socket: WebSocket | null = null;
      let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
      let stopped = false;
      const connect = () => {
        if (stopped) return;
        const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
        socket = new WebSocket(
          `${scheme}//${window.location.host}/api/v1/me/notifications/live`,
        );
        socket.onmessage = (event) => {
          try {
            const message: unknown = JSON.parse(String(event.data));
            if (isRecord(message) && message.type === "notifications_changed")
              onChange();
          } catch {
            // A live message is only an invalidation hint; malformed hints are ignored.
          }
        };
        socket.onopen = onChange;
        socket.onclose = () => {
          if (!stopped) reconnectTimer = setTimeout(connect, 1000);
        };
        socket.onerror = () => socket?.close();
      };
      connect();
      return () => {
        stopped = true;
        if (reconnectTimer !== null) clearTimeout(reconnectTimer);
        socket?.close();
      };
    },
  };
}

function validateInbox(
  value: ViewerNotificationInboxQuery["viewerNotificationInbox"],
): NotificationPage {
  const items = value.items.map((item) => {
    if (
      item.kind !== "review_approved" &&
      item.kind !== "review_rejected" &&
      item.kind !== "review_changes_requested"
    )
      throw new NotificationRequestError(200, value);
    return item as NotificationPage["items"][number];
  });
  return { ...value, items };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
