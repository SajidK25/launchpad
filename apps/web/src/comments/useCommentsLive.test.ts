/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { createElement, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { commentKeys } from "./useComments";
import {
  reconcileCommentLiveEvent,
  useCommentsLive,
  type CommentsLiveClient,
} from "./useCommentsLive";

function socket() {
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
  };
}

describe("comment live reconciliation", () => {
  it("queues roots and unloaded replies while refetching loaded-parent replies", () => {
    const queryClient = new QueryClient();
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();
    expect(
      reconcileCommentLiveEvent(queryClient, "product-1", new Set(["root-1"]), {
        type: "comment.created",
        product_id: "product-1",
        comment_id: "new-root",
        parent_id: null,
      }),
    ).toBe("notice");
    expect(
      reconcileCommentLiveEvent(queryClient, "product-1", new Set(["root-1"]), {
        type: "comment.created",
        product_id: "product-1",
        comment_id: "reply-1",
        parent_id: "root-1",
      }),
    ).toBe("reply");
    expect(
      reconcileCommentLiveEvent(queryClient, "product-1", new Set(["root-1"]), {
        type: "comment.created",
        product_id: "product-1",
        comment_id: "reply-2",
        parent_id: "root-2",
      }),
    ).toBe("notice");
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: commentKeys.replies("product-1", "root-1"),
      exact: false,
    });
  });

  it("reconciles roots and loaded replies after connect without owning drafts", async () => {
    const liveSocket = socket();
    const client: CommentsLiveClient = {
      issueLiveTicket: vi
        .fn()
        .mockResolvedValue({ ticket: "ticket", expires_at: "later" }),
      connectLive: vi.fn().mockReturnValue(liveSocket),
    };
    const queryClient = new QueryClient();
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();
    const latest = {
      current: null as ReturnType<typeof useCommentsLive> | null,
    };
    function Harness() {
      const [draft] = useState("unsent draft");
      latest.current = useCommentsLive({
        client,
        productId: "product-1",
        enabled: true,
        loadedParentIds: new Set(["root-1"]),
      });
      return createElement("span", null, draft);
    }
    const view = render(
      createElement(
        QueryClientProvider,
        { client: queryClient },
        createElement(Harness),
      ),
    );
    await waitFor(() => expect(client.connectLive).toHaveBeenCalled());
    act(() => liveSocket.open());
    expect(view.getByText("unsent draft")).toBeTruthy();
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: commentKeys.discussion("product-1"),
      exact: false,
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: commentKeys.replies("product-1", "root-1"),
      exact: false,
    });

    act(() =>
      liveSocket.message(
        JSON.stringify({
          type: "comment.created",
          product_id: "product-1",
          comment_id: "root-2",
          parent_id: null,
        }),
      ),
    );
    expect(latest.current?.newActivityCount).toBe(1);
  });

  it("closes an unavailable discussion, clears projections, and leaves local input intact", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(commentKeys.discussion("product-1"), {
      pages: [],
    });
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();
    expect(
      reconcileCommentLiveEvent(queryClient, "product-1", new Set(), {
        type: "discussion.closed",
        product_id: "product-1",
      }),
    ).toBe("closed");
    expect(
      queryClient.getQueryData(commentKeys.discussion("product-1")),
    ).toBeUndefined();
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["launches", "public-product", "product-1"],
    });
  });
});
