/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { CommentsClient, DiscussionPage, ReplyPage } from "./client";
import {
  commentKeys,
  flattenDiscussionPages,
  flattenReplyPages,
  useCreateComment,
} from "./useComments";

const author = {
  accountId: "account-1",
  displayName: "Ada",
  avatarUrl: "/avatar",
  publicProfileUrl: null,
};

function root(id: string) {
  return {
    id,
    productId: "product-1",
    parentId: null,
    body: id,
    createdAt: "2026-11-20T00:00:00Z",
    author,
    replyCount: 0,
    replies: [],
  };
}

function reply(id: string) {
  return { ...root(id), parentId: "root-1" };
}

describe("comment query state", () => {
  it("pages and deduplicates roots newest-first and replies chronologically", () => {
    const roots: DiscussionPage[] = [
      { items: [root("new"), root("middle")], nextCursor: "cursor" },
      { items: [root("middle"), root("old")], nextCursor: null },
    ];
    const replies: ReplyPage[] = [
      { items: [reply("middle"), reply("new")], earlierCursor: "cursor" },
      { items: [reply("old"), reply("middle")], earlierCursor: null },
    ];
    expect(flattenDiscussionPages(roots).map(({ id }) => id)).toEqual([
      "new",
      "middle",
      "old",
    ]);
    expect(flattenReplyPages(replies).map(({ id }) => id)).toEqual([
      "old",
      "middle",
      "new",
    ]);
  });

  it("shows only confirmed publication and reconciles through authoritative refetch", async () => {
    const result = {
      id: "comment-1",
      product_id: "product-1",
      parent_id: null,
      body: "kept draft",
      created_at: "2026-11-20T00:00:00Z",
      replayed: false,
    };
    const client = {
      createComment: vi.fn().mockResolvedValue(result),
    } as unknown as CommentsClient;
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    const { result: hook } = renderHook(
      () => useCreateComment(client, "product-1"),
      { wrapper },
    );

    expect(
      queryClient.getQueryData(commentKeys.discussion("product-1")),
    ).toBeUndefined();
    act(() =>
      hook.current.mutate({ body: "kept draft", idempotencyKey: "attempt-1" }),
    );
    await waitFor(() => expect(hook.current.data).toEqual(result));
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: commentKeys.discussion("product-1"),
      exact: false,
    });
  });
});
