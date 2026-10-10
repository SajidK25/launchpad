/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement } from "react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { ProductClient } from "./client";
import {
  productKeys,
  useApprovedReviews,
  useDecideReview,
} from "./useProducts";

function setup(client: ProductClient) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  const hook = renderHook(() => useDecideReview(client, "product-1"), {
    wrapper,
  });
  return { ...hook, invalidate };
}

describe("product review hooks", () => {
  it("loads an approved review page using its cursor in the query key", async () => {
    const page = { items: [], nextCursor: null };
    const client = {
      fetchApprovedReviews: vi.fn().mockResolvedValue(page),
    } as unknown as ProductClient;
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    const { result } = renderHook(
      () => useApprovedReviews(client, 12, "after-1"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.data).toEqual(page));
    expect(client.fetchApprovedReviews).toHaveBeenCalledWith({
      first: 12,
      after: "after-1",
    });
  });

  it("reconciles queue, approved, staff detail, and founder detail after a decision", async () => {
    const client = {
      decideReview: vi.fn().mockResolvedValue({
        decision_id: "decision-1",
        product_id: "product-1",
        submission_id: "submission-1",
        status: "approved",
        version: 4,
      }),
    } as unknown as ProductClient;
    const { result, invalidate } = setup(client);

    await act(async () =>
      result.current.mutateAsync({
        idempotencyKey: "attempt-1",
        payload: {
          submission_id: "submission-1",
          expected_version: 3,
          outcome: "approved",
        },
      }),
    );

    expect(client.decideReview).toHaveBeenCalledWith(
      "product-1",
      {
        submission_id: "submission-1",
        expected_version: 3,
        outcome: "approved",
      },
      "attempt-1",
    );
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: productKeys.reviewQueue,
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: productKeys.approvedReviews,
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: productKeys.review("product-1"),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: productKeys.detail("product-1"),
    });
  });

  it("refreshes current server details when a decision is stale", async () => {
    const conflict = Object.assign(new Error("stale review"), { status: 409 });
    const client = {
      decideReview: vi.fn().mockRejectedValue(conflict),
    } as unknown as ProductClient;
    const { result, invalidate } = setup(client);

    await act(async () => {
      await expect(
        result.current.mutateAsync({
          idempotencyKey: "attempt-2",
          payload: {
            submission_id: "submission-1",
            expected_version: 3,
            outcome: "approved",
          },
        }),
      ).rejects.toBe(conflict);
    });

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: productKeys.reviewQueue,
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: productKeys.review("product-1"),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: productKeys.detail("product-1"),
    });
  });
});
