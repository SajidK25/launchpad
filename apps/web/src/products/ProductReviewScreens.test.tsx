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
import { ProductRequestError, type ProductClient } from "./client";

const staffSession = {
  account_id: "reviewer-1",
  csrf_token: "csrf-1",
  verified: true,
  role: "reviewer" as const,
  suspended: false,
};
const founderSession = {
  account_id: "founder-1",
  csrf_token: "csrf-2",
  verified: true,
  role: "member" as const,
  suspended: false,
};

function detail(status: string, feedback: string | null = null) {
  const submission = {
    id: "submission-1",
    submittedAt: "2026-10-01T08:00:00Z",
    productVersion: 7,
  };
  const product = {
    summary: {
      id: "product-1",
      status,
      version: 7,
      name: "Quiet Harbor",
      pitch: "A calm way to plan work.",
      createdAt: "2026-10-01T07:00:00Z",
      updatedAt: "2026-10-01T08:00:00Z",
    },
    description: "A private product description.",
    websiteUrl: "https://harbor.example",
    topics: [{ id: "topic-1", displayName: "Productivity", position: 1 }],
    assets: [],
    submission,
    reviewOutcome: feedback ? { status: "changes_requested", feedback } : null,
  };
  return {
    product,
    submission,
    possibleDuplicate: false,
    founderSuspended: false,
  };
}

function harness({
  role = "staff",
  productStatus = "submitted",
  feedback = null,
  approvedItems = [],
}: {
  role?: "staff" | "founder";
  productStatus?: string;
  feedback?: string | null;
  approvedItems?: Array<{
    product: {
      id: string;
      status: string;
      version: number;
      name: string;
      pitch: string;
      createdAt: string;
      updatedAt: string;
    };
    submission: { id: string; submittedAt: string; productVersion: number };
    approvedAt: string;
  }>;
} = {}) {
  const session = role === "staff" ? staffSession : founderSession;
  const currentDetail = detail(productStatus, feedback);
  const client = {
    fetchViewerProducts: vi
      .fn()
      .mockResolvedValue({ items: [], nextCursor: null }),
    fetchViewerProduct: vi.fn().mockResolvedValue(currentDetail.product),
    fetchReviewQueue: vi
      .fn()
      .mockResolvedValue({ items: [], nextCursor: null }),
    fetchReviewProduct: vi.fn().mockResolvedValue(currentDetail),
    fetchApprovedReviews: vi.fn().mockResolvedValue({
      items: approvedItems,
      nextCursor: null,
    }),
    fetchTopicChoices: vi.fn().mockResolvedValue([]),
    decideReview: vi.fn().mockResolvedValue({
      decision_id: "decision-1",
      product_id: "product-1",
      submission_id: "submission-1",
      status: "changes_requested",
      version: 8,
    }),
    saveProduct: vi.fn().mockResolvedValue({
      id: "product-1",
      status: productStatus,
      version: 8,
    }),
    createDraft: vi.fn(),
    deleteDraft: vi.fn(),
    submitWhenReady: vi.fn(),
  } as unknown as ProductClient;
  const identity = {
    currentSession: vi.fn().mockResolvedValue(session),
    logout: vi.fn().mockResolvedValue(undefined),
    requestVerification: vi.fn(),
  } as unknown as IdentityClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);

  return {
    client,
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

describe("product review screens", () => {
  it("requires founder feedback and records a decision only after server success", async () => {
    const app = harness();
    app.view("/products/review/product-1");
    await screen.findByRole("heading", { name: "Quiet Harbor" });
    fireEvent.change(screen.getByLabelText("Decision"), {
      target: { value: "changes_requested" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Record review decision" }),
    );

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Add an explanation for the founder",
    );
    expect(app.client.decideReview).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Feedback for the founder/), {
      target: { value: "Please describe the intended customer." },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Record review decision" }),
    );

    await screen.findByText(/Decision recorded/);
    expect(app.client.decideReview).toHaveBeenCalledWith(
      "product-1",
      {
        submission_id: "submission-1",
        expected_version: 7,
        outcome: "changes_requested",
        feedback: "Please describe the intended customer.",
      },
      expect.any(String),
    );
  });

  it("keeps feedback over 2,000 characters from becoming a success", async () => {
    const app = harness();
    app.view("/products/review/product-1");
    await screen.findByRole("heading", { name: "Quiet Harbor" });
    fireEvent.change(screen.getByLabelText("Decision"), {
      target: { value: "rejected" },
    });
    fireEvent.change(screen.getByLabelText(/Feedback for the founder/), {
      target: { value: "x".repeat(2001) },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Record review decision" }),
    );

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Feedback must be 2,000 characters or fewer",
    );
    expect(app.client.decideReview).not.toHaveBeenCalled();
    expect(screen.queryByText(/Decision recorded/)).toBeNull();
  });

  it("refreshes stale decision details without showing a success state", async () => {
    const app = harness();
    vi.mocked(app.client.decideReview).mockRejectedValue(
      new ProductRequestError(409, { detail: "stale" }),
    );
    app.view("/products/review/product-1");
    await screen.findByRole("heading", { name: "Quiet Harbor" });
    fireEvent.change(screen.getByLabelText("Decision"), {
      target: { value: "rejected" },
    });
    fireEvent.change(screen.getByLabelText(/Feedback for the founder/), {
      target: { value: "The launch information is incomplete." },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Record review decision" }),
    );

    expect((await screen.findByRole("alert")).textContent).toContain(
      "changed after you opened it",
    );
    expect(screen.queryByText(/Decision recorded/)).toBeNull();
    await waitFor(() =>
      expect(app.client.fetchReviewProduct).toHaveBeenCalledTimes(2),
    );
  });

  it("finds approved products and offers only the return-for-changes action", async () => {
    const item = {
      product: {
        id: "product-1",
        status: "approved",
        version: 7,
        name: "Quiet Harbor",
        pitch: "A calm way to plan work.",
        createdAt: "2026-10-01T07:00:00Z",
        updatedAt: "2026-10-01T08:00:00Z",
      },
      submission: {
        id: "submission-1",
        submittedAt: "2026-10-01T08:00:00Z",
        productVersion: 7,
      },
      approvedAt: "2026-10-01T09:00:00Z",
    };
    const app = harness({ productStatus: "approved", approvedItems: [item] });
    app.view("/products/review");
    const approved = await screen.findByRole("list", {
      name: "Approved products",
    });
    expect(
      within(approved)
        .getByRole("link", { name: /Quiet Harbor/ })
        .getAttribute("href"),
    ).toBe("/products/review/product-1");

    cleanup();
    app.view("/products/review/product-1");
    await screen.findByRole("heading", { name: "Quiet Harbor" });
    const decision = screen.getByLabelText("Decision") as HTMLSelectElement;
    expect(Array.from(decision.options).map((option) => option.value)).toEqual([
      "changes_requested",
    ]);
    expect(screen.queryByRole("option", { name: "Approve" })).toBeNull();
    fireEvent.change(screen.getByLabelText(/Feedback for the founder/), {
      target: { value: "Please correct the pricing details." },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Record review decision" }),
    );
    await screen.findByText(/Decision recorded/);
    expect(app.client.decideReview).toHaveBeenCalledWith(
      "product-1",
      expect.objectContaining({ outcome: "changes_requested" }),
      expect.any(String),
    );
  });

  it("lets founders edit a requested correction and keeps it out of delete", async () => {
    const app = harness({
      role: "founder",
      productStatus: "changes_requested",
      feedback: "Please clarify who this is for.",
    });
    app.view("/products/product-1");
    expect(
      await screen.findByText("Please clarify who this is for."),
    ).not.toBeNull();
    const name = screen.getByLabelText(/Name/);
    expect((name as HTMLInputElement).disabled).toBe(false);
    fireEvent.change(name, { target: { value: "Quiet Harbor Updated" } });
    await waitFor(() => expect(app.client.saveProduct).toHaveBeenCalled());
    expect(
      (
        screen.getByRole("button", {
          name: "Submit for staff review",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
    expect(
      screen.queryByRole("button", { name: /Delete private draft/ }),
    ).toBeNull();
  });

  it.each([
    ["approved", "Approved · private"],
    ["rejected", "Rejected"],
  ])("keeps %s products read-only for founders", async (status, label) => {
    const app = harness({
      role: "founder",
      productStatus: status,
      feedback: "This feedback remains in the audit trail.",
    });
    app.view("/products/product-1");
    expect(await screen.findByText(label)).not.toBeNull();
    expect(
      screen.getByText("This feedback remains in the audit trail."),
    ).not.toBeNull();
    expect(screen.queryByLabelText("Name")).toBeNull();
    expect(
      screen.queryByRole("button", { name: /delete|submit for staff review/i }),
    ).toBeNull();
  });
});
