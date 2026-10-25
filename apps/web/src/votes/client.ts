import type { components } from "@launchpad/contracts";
import type { IdentityClient } from "../identity/client";

type VoteResponse = components["schemas"]["VoteResponse"];
type VoteInput = components["schemas"]["VoteInput"];
type Fetcher = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export class VoteRequestError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`Vote request failed with status ${status}.`);
    this.name = "VoteRequestError";
  }
}

export function createVoteClient(
  fetcher: Fetcher = globalThis.fetch.bind(globalThis),
  identity: Pick<IdentityClient, "ensureSession" | "getCsrfToken">,
) {
  async function command(
    path: string,
    method: "POST" | "DELETE",
    idempotencyKey: string,
    turnstileToken?: string,
    body?: VoteInput,
  ): Promise<VoteResponse> {
    await identity.ensureSession();
    const headers: Record<string, string> = {
      "Idempotency-Key": idempotencyKey,
    };
    const csrfToken = identity.getCsrfToken();
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
    if (turnstileToken) headers["X-Turnstile-Token"] = turnstileToken;
    if (body) headers["Content-Type"] = "application/json";
    const response = await fetcher(path, {
      method,
      credentials: "include",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const value: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const detail =
        typeof value === "object" &&
        value !== null &&
        "detail" in value &&
        typeof value.detail === "string"
          ? value.detail
          : "Vote could not be completed.";
      throw new VoteRequestError(response.status, detail);
    }
    if (!isVoteResponse(value))
      throw new VoteRequestError(response.status, "Vote response was invalid.");
    return value;
  }

  return {
    cast: (
      productId: string,
      idempotencyKey: string,
      turnstileToken?: string,
    ) =>
      command("/api/v1/votes", "POST", idempotencyKey, turnstileToken, {
        product_id: productId,
      }),
    withdraw: (
      productId: string,
      idempotencyKey: string,
      turnstileToken?: string,
    ) =>
      command(
        `/api/v1/votes/${encodeURIComponent(productId)}`,
        "DELETE",
        idempotencyKey,
        turnstileToken,
      ),
  };
}

function isVoteResponse(value: unknown): value is VoteResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    "vote_id" in value &&
    typeof value.vote_id === "string" &&
    "product_id" in value &&
    typeof value.product_id === "string" &&
    "active" in value &&
    typeof value.active === "boolean" &&
    "cast_at" in value &&
    typeof value.cast_at === "string" &&
    "replayed" in value &&
    typeof value.replayed === "boolean"
  );
}
