import { describe, expect, it, vi } from "vitest";
import { CommentRequestError, createCommentsClient } from "./client";

function identity() {
  return {
    ensureSession: vi.fn().mockResolvedValue({}),
    getCsrfToken: vi.fn().mockReturnValue("csrf-token"),
  };
}

describe("comments client", () => {
  it("sends secured idempotent comment commands", async () => {
    const response = {
      id: "comment-1",
      product_id: "product-1",
      parent_id: null,
      body: "Useful feedback",
      created_at: "2026-11-20T00:00:00Z",
      replayed: false,
    };
    const fetcher = vi
      .fn()
      .mockResolvedValue(Response.json(response, { status: 201 }));
    const auth = identity();
    const client = createCommentsClient(fetcher, auth);

    await expect(
      client.createComment("product-1", "Useful feedback", "attempt-1"),
    ).resolves.toEqual(response);
    expect(auth.ensureSession).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/products/product-1/comments",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "attempt-1",
          "X-CSRF-Token": "csrf-token",
        },
        body: JSON.stringify({ body: "Useful feedback" }),
      }),
    );
  });

  it("distinguishes replayed, limited, conflict, and retryable outcomes", async () => {
    const replayed = createCommentsClient(
      vi.fn().mockResolvedValue(
        Response.json(
          {
            id: "comment-1",
            product_id: "product-1",
            parent_id: null,
            body: "Useful feedback",
            created_at: "2026-11-20T00:00:00Z",
            replayed: true,
          },
          { status: 200 },
        ),
      ),
      identity(),
    );
    await expect(
      replayed.createComment("product-1", "Useful feedback", "same-key"),
    ).resolves.toMatchObject({ replayed: true });

    for (const [status, kind] of [
      [429, "limited"],
      [409, "conflict"],
      [503, "retryable"],
    ] as const) {
      const client = createCommentsClient(
        vi.fn().mockResolvedValue(
          Response.json(
            { detail: `safe ${kind}` },
            {
              status,
              headers: status === 429 ? { "Retry-After": "60" } : {},
            },
          ),
        ),
        identity(),
      );
      await expect(
        client.createComment("product-1", "draft", "key"),
      ).rejects.toMatchObject({
        kind,
        retryAfter: status === 429 ? 60 : null,
      } satisfies Partial<CommentRequestError>);
    }
  });

  it("uses generated GraphQL operations for bounded root and reply pages", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({
          data: { productDiscussion: { items: [], nextCursor: "next" } },
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          data: { commentReplies: { items: [], earlierCursor: null } },
        }),
      );
    const client = createCommentsClient(fetcher, identity());
    await client.fetchDiscussion({ productId: "product-1", first: 20 });
    await client.fetchReplies({
      productId: "product-1",
      parentId: "root-1",
      first: 20,
    });

    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "/api/v1/graphql",
      expect.objectContaining({
        body: expect.stringContaining("ProductDiscussion"),
      }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "/api/v1/graphql",
      expect.objectContaining({
        body: expect.stringContaining("CommentReplies"),
      }),
    );
  });
});
