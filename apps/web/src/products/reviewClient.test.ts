import { describe, expect, it, vi } from "vitest";

import { createProductClient } from "./client";

describe("product review client", () => {
  it("reads the approved review page through its generated GraphQL operation", async () => {
    const page = { items: [], nextCursor: "next" };
    const fetcher = vi.fn().mockResolvedValue(
      Response.json({ data: { approvedReviews: page } }),
    );
    const client = createProductClient(fetcher, {
      ensureSession: vi.fn().mockResolvedValue({}),
      getCsrfToken: vi.fn().mockReturnValue(null),
    });

    await expect(
      client.fetchApprovedReviews({ first: 10, after: "cursor-1" }),
    ).resolves.toEqual(page);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/graphql",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: expect.stringContaining('"first":10,"after":"cursor-1"'),
      }),
    );
    expect(JSON.parse(fetcher.mock.calls[0][1].body).query).toContain(
      "approvedReviews",
    );
  });

  it("keeps every server product status distinct", async () => {
    const fetcher = vi.fn();
    const client = createProductClient(fetcher, {
      ensureSession: vi.fn().mockResolvedValue({}),
      getCsrfToken: vi.fn().mockReturnValue("csrf-token"),
    });
    const statuses = [
      "draft",
      "submitted",
      "changes_requested",
      "approved",
      "rejected",
    ] as const;

    for (const status of statuses) {
      fetcher.mockResolvedValueOnce(
        Response.json({ id: "product-1", status, version: 5 }),
      );
      await expect(
        client.saveProduct("product-1", { version: 4 }),
      ).resolves.toMatchObject({ status });
    }
  });

  it("posts the full decision identity with CSRF and idempotency protection", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      Response.json({
        decision_id: "decision-1",
        product_id: "product / one",
        submission_id: "submission-1",
        status: "changes_requested",
        version: 8,
      }),
    );
    const identity = {
      ensureSession: vi.fn().mockResolvedValue({}),
      getCsrfToken: vi.fn().mockReturnValue("csrf-token"),
    };
    const client = createProductClient(fetcher, identity);

    await expect(
      client.decideReview(
        "product / one",
        {
          submission_id: "submission-1",
          expected_version: 7,
          outcome: "changes_requested",
          feedback: "Please add the missing details.",
        },
        "review-attempt-42",
      ),
    ).resolves.toEqual({
      decision_id: "decision-1",
      product_id: "product / one",
      submission_id: "submission-1",
      status: "changes_requested",
      version: 8,
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/staff/products/product%20%2F%20one/review-decisions",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": "csrf-token",
          "Idempotency-Key": "review-attempt-42",
        },
        body: JSON.stringify({
          submission_id: "submission-1",
          expected_version: 7,
          outcome: "changes_requested",
          feedback: "Please add the missing details.",
        }),
      }),
    );
    expect(identity.ensureSession).toHaveBeenCalledOnce();
  });
});
