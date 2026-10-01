/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { createElement } from "react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { IdentityClient } from "../identity/client";
import { ProductRoutes } from "./ProductScreens";
import type { ProductClient } from "./client";

const staffSession = {
  account_id: "reviewer-1",
  csrf_token: "csrf-1",
  verified: true,
  role: "reviewer" as const,
  suspended: false,
};
type SessionOverrides = {
  role?: "member" | "reviewer" | "admin";
  verified?: boolean;
  suspended?: boolean;
};

function queueItem(
  id: string,
  submittedAt: string,
  flags: { possibleDuplicate?: boolean; founderSuspended?: boolean } = {},
) {
  return {
    product: {
      id,
      status: "submitted",
      version: 3,
      name: `Product ${id}`,
      pitch: `Pitch for ${id}`,
      createdAt: submittedAt,
      updatedAt: submittedAt,
    },
    submission: {
      id: `submission-${id}`,
      submittedAt,
      productVersion: 3,
    },
    possibleDuplicate: flags.possibleDuplicate ?? false,
    founderSuspended: flags.founderSuspended ?? false,
  };
}

function reviewProduct(
  overrides: {
    possibleDuplicate?: boolean;
    founderSuspended?: boolean;
    name?: string;
    productVersion?: number;
  } = {},
) {
  const submission = {
    id: "submission-product-1",
    submittedAt: "2026-10-01T08:00:00Z",
    productVersion: overrides.productVersion ?? 5,
  };
  return {
    product: {
      summary: {
        id: "product-1",
        status: "submitted",
        version: 5,
        name: overrides.name ?? "Current product name",
        pitch: "Current product pitch",
        createdAt: "2026-10-01T07:00:00Z",
        updatedAt: "2026-10-01T08:00:00Z",
      },
      description: "Current full product description.",
      websiteUrl: "https://product.example",
      topics: [{ id: "topic-1", displayName: "AI Tools", position: 1 }],
      assets: [
        {
          id: "logo-1",
          kind: "logo",
          mediaType: "image/png",
          byteCount: 2048,
          url: "/api/v1/products/product-1/assets/logo-1?signature=test",
        },
        {
          id: "shot-1",
          kind: "screenshot",
          mediaType: "image/webp",
          byteCount: 4096,
          url: "/api/v1/products/product-1/assets/shot-1?signature=test",
        },
      ],
      submission,
    },
    submission,
    possibleDuplicate: overrides.possibleDuplicate ?? false,
    founderSuspended: overrides.founderSuspended ?? false,
  };
}

function fixture(
  sessionOverrides: SessionOverrides = {},
  queuePages: Array<{
    items: ReturnType<typeof queueItem>[];
    nextCursor: string | null;
  }> = [{ items: [], nextCursor: null }],
  detail: ReturnType<typeof reviewProduct> | null = reviewProduct(),
) {
  const client = {
    fetchViewerProducts: vi
      .fn()
      .mockResolvedValue({ items: [], nextCursor: null }),
    fetchReviewQueue: vi
      .fn()
      .mockImplementation(async (variables?: { after?: string | null }) => {
        const index = variables?.after ? 1 : 0;
        return queuePages[index] ?? { items: [], nextCursor: null };
      }),
    fetchReviewProduct: vi.fn().mockResolvedValue(detail),
  } as unknown as ProductClient;
  const identity = {
    currentSession: vi
      .fn()
      .mockResolvedValue({ ...staffSession, ...sessionOverrides }),
    logout: vi.fn().mockResolvedValue(undefined),
  } as unknown as IdentityClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);

  return {
    client,
    identity,
    view(path: string) {
      return render(
        <ProductRoutes client={client} identityClient={identity} path={path} />,
        { wrapper },
      );
    },
  };
}

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

describe("staff review screens", () => {
  it.each([
    ["member", { role: "member" as const, verified: true, suspended: false }],
    [
      "unverified reviewer",
      { role: "reviewer" as const, verified: false, suspended: false },
    ],
    [
      "suspended reviewer",
      { role: "reviewer" as const, verified: true, suspended: true },
    ],
  ])("keeps the review queue unavailable to a %s", async (_label, session) => {
    const app = fixture(session);
    app.view("/products/review");

    expect(
      await screen.findByRole("heading", { name: "Staff review queue" }),
    ).not.toBeNull();
    expect(screen.getByRole("alert").textContent).toContain(
      "not available for your account",
    );
    expect(app.client.fetchReviewQueue).not.toHaveBeenCalled();
  });

  it("shows sign-in for a visitor and does not issue a staff read", async () => {
    const app = fixture();
    vi.mocked(app.identity.currentSession).mockRejectedValue(
      new Error("unauthenticated"),
    );
    app.view("/products/review");

    expect(
      await screen.findByRole("button", { name: "Sign in" }),
    ).not.toBeNull();
    expect(app.client.fetchReviewQueue).not.toHaveBeenCalled();
  });

  it("shows the oldest-first page and staff-only flags, with keyboard-operable entries", async () => {
    const app = fixture({}, [
      {
        items: [
          queueItem("oldest", "2026-09-29T08:00:00Z"),
          queueItem("next", "2026-09-30T08:00:00Z", {
            possibleDuplicate: true,
            founderSuspended: true,
          }),
        ],
        nextCursor: null,
      },
    ]);
    app.view("/products/review");

    const list = await screen.findByRole("list", {
      name: "Pending submissions, oldest first",
    });
    const cards = within(list).getAllByRole("link");
    expect(cards[0].textContent).toContain("Product oldest");
    expect(cards[1].textContent).toContain("Product next");
    expect(cards[1].textContent).toContain("Possible duplicate website");
    expect(cards[1].textContent).toContain("Founder suspended");
    cards[0].focus();
    expect(document.activeElement).toBe(cards[0]);
    expect(app.client.fetchReviewQueue).toHaveBeenCalledWith({
      first: 20,
      after: null,
    });
  });

  it("navigates keyset pages without duplicating queue cards", async () => {
    const app = fixture({}, [
      {
        items: [queueItem("first-page", "2026-09-29T08:00:00Z")],
        nextCursor: "cursor-page-two",
      },
      {
        items: [queueItem("second-page", "2026-09-30T08:00:00Z")],
        nextCursor: null,
      },
    ]);
    app.view("/products/review");
    await screen.findByText("Product first-page");

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Product second-page")).not.toBeNull();
    expect(screen.queryByText("Product first-page")).toBeNull();
    expect(app.client.fetchReviewQueue).toHaveBeenLastCalledWith({
      first: 20,
      after: "cursor-page-two",
    });

    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    expect(await screen.findByText("Product first-page")).not.toBeNull();
    expect(screen.queryByText("Product second-page")).toBeNull();
  });

  it("shows the current detail, private media, submission version, and flags without moderation actions", async () => {
    const app = fixture(
      {},
      [{ items: [], nextCursor: null }],
      reviewProduct({ possibleDuplicate: true, founderSuspended: true }),
    );
    app.view("/products/review/product-1");

    expect(
      await screen.findByRole("heading", { name: "Current product name" }),
    ).not.toBeNull();
    expect(
      screen.getByText("Current full product description."),
    ).not.toBeNull();
    expect(
      screen.getByRole("link", { name: "https://product.example" }),
    ).not.toBeNull();
    expect(screen.getByText("AI Tools")).not.toBeNull();
    expect(
      screen.getByRole("img", { name: "Product logo" }).getAttribute("src"),
    ).toContain("/api/v1/products/product-1/assets/logo-1");
    expect(screen.getByText("Founder account suspended")).not.toBeNull();
    expect(screen.getByText("Possible duplicate website")).not.toBeNull();
    expect(screen.getByText("submission-product-1")).not.toBeNull();
    expect(
      screen.getByText("Current product version").parentElement?.textContent,
    ).toContain("5");
    expect(
      screen.getByText("Submission version").parentElement?.textContent,
    ).toContain("5");
    expect(app.client.fetchReviewProduct).toHaveBeenCalledWith({
      id: "product-1",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh current details" }),
    );
    await waitFor(() =>
      expect(app.client.fetchReviewProduct).toHaveBeenCalledTimes(2),
    );
    for (const label of [
      "Approve",
      "Reject",
      "Request changes",
      "Schedule",
      "Launch",
    ]) {
      expect(
        screen.queryByRole("button", { name: new RegExp(label, "i") }),
      ).toBeNull();
    }
  });

  it("hides a withdrawn submission when the current detail projection is absent", async () => {
    const app = fixture({}, [{ items: [], nextCursor: null }], null);
    app.view("/products/review/product-1");

    expect(
      await screen.findByRole("heading", {
        name: "Submission no longer pending",
      }),
    ).not.toBeNull();
    expect(screen.queryByText("Current full product description.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Refresh submission" }));
    await waitFor(() =>
      expect(app.client.fetchReviewProduct).toHaveBeenCalledTimes(2),
    );
  });

  it("offers a queue link only to verified, active staff", async () => {
    const staff = fixture();
    staff.view("/products");
    expect(
      await screen.findByRole("link", { name: "Open staff review queue" }),
    ).not.toBeNull();

    cleanup();
    const member = fixture({ role: "member" });
    member.view("/products");
    await screen.findByRole("heading", { name: "Your products" });
    expect(
      screen.queryByRole("link", { name: "Open staff review queue" }),
    ).toBeNull();
  });
});
