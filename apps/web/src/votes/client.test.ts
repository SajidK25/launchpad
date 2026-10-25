import { describe, expect, it, vi } from "vitest";
import { createVoteClient, VoteRequestError } from "./client";

const voteResponse = {
  vote_id: "vote-1",
  product_id: "product-1",
  active: true,
  cast_at: "2026-10-25T00:00:00Z",
  replayed: false,
};

function identity() {
  return {
    ensureSession: vi.fn().mockResolvedValue({}),
    getCsrfToken: vi.fn().mockReturnValue("csrf-token"),
  };
}

describe("vote client", () => {
  it("sends a session-authenticated cast with CSRF, idempotency, and challenge headers", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(Response.json(voteResponse, { status: 200 }));
    const auth = identity();
    const client = createVoteClient(fetcher, auth);

    await expect(
      client.cast("product-1", "attempt-key", "turnstile-token"),
    ).resolves.toEqual(voteResponse);

    expect(auth.ensureSession).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/votes",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: {
          "Idempotency-Key": "attempt-key",
          "X-CSRF-Token": "csrf-token",
          "X-Turnstile-Token": "turnstile-token",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ product_id: "product-1" }),
      }),
    );
  });

  it("sends a withdrawal command with its own retry key", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        Response.json({ ...voteResponse, active: false }, { status: 200 }),
      );
    const client = createVoteClient(fetcher, identity());

    await expect(
      client.withdraw("product-1", "remove-key"),
    ).resolves.toMatchObject({
      active: false,
      product_id: "product-1",
    });

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/votes/product-1",
      expect.objectContaining({
        method: "DELETE",
        headers: {
          "Idempotency-Key": "remove-key",
          "X-CSRF-Token": "csrf-token",
        },
        body: undefined,
      }),
    );
  });

  it("maps safe server errors and rejects malformed success bodies", async () => {
    const challenge = createVoteClient(
      vi
        .fn()
        .mockResolvedValue(
          Response.json(
            { detail: "complete the security check and retry" },
            { status: 422 },
          ),
        ),
      identity(),
    );
    await expect(challenge.cast("product-1", "same-key")).rejects.toMatchObject(
      {
        name: "VoteRequestError",
        status: 422,
        detail: "complete the security check and retry",
      } satisfies Partial<VoteRequestError>,
    );

    const malformed = createVoteClient(
      vi.fn().mockResolvedValue(Response.json({ active: true })),
      identity(),
    );
    await expect(malformed.cast("product-1", "key")).rejects.toMatchObject({
      status: 200,
      detail: "Vote response was invalid.",
    });
  });
});
