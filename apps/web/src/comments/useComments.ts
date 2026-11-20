import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
import type {
  CommentCommandResult,
  CommentsClient,
  DiscussionEntry,
  DiscussionPage,
  DiscussionThread,
  ReplyPage,
} from "./client";

export const commentKeys = {
  all: ["comments"] as const,
  product: (productId: string) => ["comments", productId] as const,
  discussion: (productId: string, first = 20) =>
    ["comments", productId, "roots", first] as const,
  repliesRoot: (productId: string) =>
    ["comments", productId, "replies"] as const,
  replies: (productId: string, parentId: string, first = 20) =>
    ["comments", productId, "replies", parentId, first] as const,
};

export function useDiscussion(
  client: CommentsClient,
  productId: string,
  first = 20,
  enabled = true,
) {
  return useInfiniteQuery<
    DiscussionPage,
    Error,
    InfiniteData<DiscussionPage, string | null>,
    ReturnType<typeof commentKeys.discussion>,
    string | null
  >({
    queryKey: commentKeys.discussion(productId, first),
    enabled: enabled && productId.length > 0,
    initialPageParam: null,
    queryFn: ({ pageParam, signal }) =>
      client.fetchDiscussion(
        { productId, first, after: pageParam ?? undefined },
        signal,
      ),
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });
}

export function useCommentReplies(
  client: CommentsClient,
  productId: string,
  parentId: string,
  first = 20,
  enabled = true,
) {
  return useInfiniteQuery<
    ReplyPage,
    Error,
    InfiniteData<ReplyPage, string | null>,
    ReturnType<typeof commentKeys.replies>,
    string | null
  >({
    queryKey: commentKeys.replies(productId, parentId, first),
    enabled: enabled && productId.length > 0 && parentId.length > 0,
    initialPageParam: null,
    queryFn: ({ pageParam, signal }) =>
      client.fetchReplies(
        { productId, parentId, first, before: pageParam ?? undefined },
        signal,
      ),
    getNextPageParam: (page) => page.earlierCursor ?? undefined,
  });
}

type CommandInput = { body: string; idempotencyKey: string };

export function useCreateComment(client: CommentsClient, productId: string) {
  const queryClient = useQueryClient();
  return useMutation<CommentCommandResult, Error, CommandInput>({
    mutationFn: ({ body, idempotencyKey }) =>
      client.createComment(productId, body, idempotencyKey),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: commentKeys.discussion(productId),
        exact: false,
      });
    },
  });
}

export function useCreateReply(
  client: CommentsClient,
  productId: string,
  parentId: string,
) {
  const queryClient = useQueryClient();
  return useMutation<CommentCommandResult, Error, CommandInput>({
    mutationFn: ({ body, idempotencyKey }) =>
      client.createReply(productId, parentId, body, idempotencyKey),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: commentKeys.replies(productId, parentId),
          exact: false,
        }),
        queryClient.invalidateQueries({
          queryKey: commentKeys.discussion(productId),
          exact: false,
        }),
      ]);
    },
  });
}

export function flattenDiscussionPages(
  pages: readonly DiscussionPage[],
): DiscussionThread[] {
  return uniqueById(pages.flatMap((page) => page.items));
}

export function flattenReplyPages(
  pages: readonly ReplyPage[],
): DiscussionEntry[] {
  return uniqueById([...pages].reverse().flatMap((page) => page.items));
}

function uniqueById<T extends { id: string }>(entries: readonly T[]): T[] {
  const seen = new Set<string>();
  return entries.filter((entry) => {
    if (seen.has(entry.id)) return false;
    seen.add(entry.id);
    return true;
  });
}
