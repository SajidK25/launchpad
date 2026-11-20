import type { components } from "@launchpad/contracts";
import {
  COMMENT_REPLIES_QUERY,
  PRODUCT_DISCUSSION_QUERY,
  type CommentRepliesQuery,
  type CommentRepliesQueryVariables,
  type ProductDiscussionQuery,
  type ProductDiscussionQueryVariables,
} from "@launchpad/contracts/src/graphql.generated";
import type { IdentityClient } from "../identity/client";

type Schemas = components["schemas"];
type Fetcher = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export type CommentCommandResult = Schemas["CommentResponse"];
export type CommentLiveTicket = Schemas["CommentLiveTicketResponse"];
export type DiscussionPage = ProductDiscussionQuery["productDiscussion"];
export type DiscussionThread = DiscussionPage["items"][number];
export type ReplyPage = CommentRepliesQuery["commentReplies"];
export type DiscussionEntry = ReplyPage["items"][number];

export type CommentErrorKind =
  | "invalid"
  | "unauthorized"
  | "forbidden"
  | "unavailable"
  | "conflict"
  | "limited"
  | "retryable"
  | "unknown";

export class CommentRequestError extends Error {
  constructor(
    readonly status: number,
    readonly kind: CommentErrorKind,
    readonly detail: string,
    readonly retryAfter: number | null = null,
  ) {
    super(detail);
    this.name = "CommentRequestError";
  }
}

export interface CommentLiveSocket {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  close: () => void;
}

export function createCommentsClient(
  fetcher: Fetcher = globalThis.fetch.bind(globalThis),
  identity: Pick<IdentityClient, "ensureSession" | "getCsrfToken">,
  socketFactory: (url: string) => CommentLiveSocket = (url) =>
    new WebSocket(url),
) {
  async function graphql<T>(
    query: string,
    variables: object,
    signal?: AbortSignal,
  ): Promise<T> {
    const response = await fetcher("/api/v1/graphql", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variables }),
      signal,
    });
    const value: unknown = await response.json().catch(() => null);
    if (!response.ok || !isRecord(value)) throw requestError(response, value);
    const result = value as { data?: T; errors?: unknown[] };
    if (result.data === undefined || result.errors?.length)
      throw new CommentRequestError(
        response.status,
        "unavailable",
        "Discussion is unavailable.",
      );
    return result.data;
  }

  async function command(path: string, body: string, idempotencyKey: string) {
    await identity.ensureSession();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    };
    const csrf = identity.getCsrfToken();
    if (csrf !== null) headers["X-CSRF-Token"] = csrf;
    const response = await fetcher(path, {
      method: "POST",
      credentials: "include",
      headers,
      body: JSON.stringify({ body }),
    });
    const value: unknown = await response.json().catch(() => null);
    if (!response.ok || !isCommentResult(value))
      throw requestError(response, value);
    return value;
  }

  return {
    fetchDiscussion: async (
      variables: ProductDiscussionQueryVariables,
      signal?: AbortSignal,
    ) =>
      (
        await graphql<ProductDiscussionQuery>(
          PRODUCT_DISCUSSION_QUERY,
          variables,
          signal,
        )
      ).productDiscussion,
    fetchReplies: async (
      variables: CommentRepliesQueryVariables,
      signal?: AbortSignal,
    ) =>
      (
        await graphql<CommentRepliesQuery>(
          COMMENT_REPLIES_QUERY,
          variables,
          signal,
        )
      ).commentReplies,
    createComment: (productId: string, body: string, idempotencyKey: string) =>
      command(
        `/api/v1/products/${encodeURIComponent(productId)}/comments`,
        body,
        idempotencyKey,
      ),
    createReply: (
      productId: string,
      parentId: string,
      body: string,
      idempotencyKey: string,
    ) =>
      command(
        `/api/v1/products/${encodeURIComponent(productId)}/comments/${encodeURIComponent(parentId)}/replies`,
        body,
        idempotencyKey,
      ),
    issueLiveTicket: async (productId: string): Promise<CommentLiveTicket> => {
      const response = await fetcher(
        `/api/v1/products/${encodeURIComponent(productId)}/comments/live-ticket`,
        { method: "POST", credentials: "include" },
      );
      const value: unknown = await response.json().catch(() => null);
      if (!response.ok || !isLiveTicket(value))
        throw requestError(response, value);
      return value;
    },
    connectLive: (ticket: string) => {
      const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
      return socketFactory(
        `${scheme}//${window.location.host}/api/v1/comments/live?ticket=${encodeURIComponent(ticket)}`,
      );
    },
  };
}

export type CommentsClient = ReturnType<typeof createCommentsClient>;

function requestError(response: Response, value: unknown): CommentRequestError {
  const detail =
    isRecord(value) && typeof value.detail === "string"
      ? value.detail
      : response.status >= 500
        ? "Discussion is temporarily unavailable. Try again."
        : "The comment request could not be completed.";
  const retryHeader = response.headers.get("Retry-After");
  const retryAfter =
    retryHeader === null ? null : Number.parseInt(retryHeader, 10);
  return new CommentRequestError(
    response.status,
    errorKind(response.status),
    detail,
    Number.isFinite(retryAfter) ? retryAfter : null,
  );
}

function errorKind(status: number): CommentErrorKind {
  if (status === 400 || status === 422) return "invalid";
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "unavailable";
  if (status === 409) return "conflict";
  if (status === 429) return "limited";
  if (status >= 500) return "retryable";
  return "unknown";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isCommentResult(value: unknown): value is CommentCommandResult {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.product_id === "string" &&
    (typeof value.parent_id === "string" || value.parent_id === null) &&
    typeof value.body === "string" &&
    typeof value.created_at === "string" &&
    typeof value.replayed === "boolean"
  );
}

function isLiveTicket(value: unknown): value is CommentLiveTicket {
  return (
    isRecord(value) &&
    typeof value.ticket === "string" &&
    value.ticket.length > 0 &&
    typeof value.expires_at === "string"
  );
}
