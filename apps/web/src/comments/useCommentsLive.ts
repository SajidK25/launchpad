import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { launchKeys } from "../launches/useLaunches";
import type { CommentLiveSocket, CommentsClient } from "./client";
import { commentKeys } from "./useComments";

export type CommentLiveEvent =
  | {
      type: "comment.created";
      product_id: string;
      comment_id: string;
      parent_id: string | null;
    }
  | { type: "discussion.closed"; product_id: string };

export type CommentsLiveClient = Pick<
  CommentsClient,
  "issueLiveTicket" | "connectLive"
>;

export function useCommentsLive({
  client,
  productId,
  enabled,
  loadedParentIds,
}: {
  client: CommentsLiveClient;
  productId: string;
  enabled: boolean;
  loadedParentIds: ReadonlySet<string>;
}) {
  const queryClient = useQueryClient();
  const loadedParents = useRef(loadedParentIds);
  const [newActivityCount, setNewActivityCount] = useState(0);
  const [connected, setConnected] = useState(false);
  const [closed, setClosed] = useState(false);
  loadedParents.current = loadedParentIds;

  const showNewActivity = useCallback(async () => {
    await queryClient.invalidateQueries({
      queryKey: commentKeys.discussion(productId),
      exact: false,
    });
    setNewActivityCount(0);
  }, [productId, queryClient]);

  useEffect(() => {
    if (!enabled || closed || productId.length === 0) return;
    let stopped = false;
    let socket: CommentLiveSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let failures = 0;

    const reconcileLoaded = () => {
      void queryClient.invalidateQueries({
        queryKey: commentKeys.discussion(productId),
        exact: false,
      });
      for (const parentId of loadedParents.current) {
        void queryClient.invalidateQueries({
          queryKey: commentKeys.replies(productId, parentId),
          exact: false,
        });
      }
    };

    const stopForClosure = () => {
      stopped = true;
      setClosed(true);
      setConnected(false);
      queryClient.removeQueries({ queryKey: commentKeys.product(productId) });
      void queryClient.invalidateQueries({
        queryKey: launchKeys.publicProduct(productId),
      });
      socket?.close();
    };

    const handle = (event: CommentLiveEvent) => {
      if (event.product_id !== productId) return;
      if (event.type === "discussion.closed") {
        stopForClosure();
        return;
      }
      if (event.parent_id === null) {
        setNewActivityCount((count) => count + 1);
      } else if (loadedParents.current.has(event.parent_id)) {
        void queryClient.invalidateQueries({
          queryKey: commentKeys.replies(productId, event.parent_id),
          exact: false,
        });
        void queryClient.invalidateQueries({
          queryKey: commentKeys.discussion(productId),
          exact: false,
        });
      } else {
        setNewActivityCount((count) => count + 1);
      }
    };

    const scheduleReconnect = () => {
      setConnected(false);
      if (stopped || reconnectTimer !== null) return;
      failures += 1;
      reconnectTimer = setTimeout(
        () => {
          reconnectTimer = null;
          void connect();
        },
        Math.min(30_000, 1_000 * 2 ** Math.min(failures - 1, 5)),
      );
    };

    const connect = async () => {
      if (stopped) return;
      try {
        const { ticket } = await client.issueLiveTicket(productId);
        if (stopped) return;
        socket = client.connectLive(ticket);
      } catch {
        scheduleReconnect();
        return;
      }
      socket.onopen = () => {
        failures = 0;
        setConnected(true);
        reconcileLoaded();
      };
      socket.onmessage = (message) => {
        const event = parseCommentLiveEvent(message.data);
        if (event !== null) handle(event);
      };
      socket.onclose = scheduleReconnect;
      socket.onerror = () => socket?.close();
    };

    void connect();
    return () => {
      stopped = true;
      setConnected(false);
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [client, closed, enabled, productId, queryClient]);

  return { connected, closed, newActivityCount, showNewActivity };
}

export function reconcileCommentLiveEvent(
  queryClient: QueryClient,
  productId: string,
  loadedParentIds: ReadonlySet<string>,
  event: CommentLiveEvent,
): "ignored" | "notice" | "reply" | "closed" {
  if (event.product_id !== productId) return "ignored";
  if (event.type === "discussion.closed") {
    queryClient.removeQueries({ queryKey: commentKeys.product(productId) });
    void queryClient.invalidateQueries({
      queryKey: launchKeys.publicProduct(productId),
    });
    return "closed";
  }
  if (event.parent_id === null || !loadedParentIds.has(event.parent_id))
    return "notice";
  void queryClient.invalidateQueries({
    queryKey: commentKeys.replies(productId, event.parent_id),
    exact: false,
  });
  return "reply";
}

export function parseCommentLiveEvent(value: unknown): CommentLiveEvent | null {
  if (typeof value !== "string") return null;
  try {
    const event: unknown = JSON.parse(value);
    if (!isRecord(event) || typeof event.product_id !== "string") return null;
    if (event.type === "discussion.closed") {
      return { type: event.type, product_id: event.product_id };
    }
    if (
      event.type === "comment.created" &&
      typeof event.comment_id === "string" &&
      (typeof event.parent_id === "string" || event.parent_id === null)
    ) {
      return {
        type: event.type,
        product_id: event.product_id,
        comment_id: event.comment_id,
        parent_id: event.parent_id,
      };
    }
  } catch {
    // Frames are invalidation hints; malformed values are safely ignored.
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
