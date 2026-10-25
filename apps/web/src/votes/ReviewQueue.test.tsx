/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IdentityClient } from "../identity/client";
import { VoteReviewRequestError, VoteReviewQueue } from "./ReviewQueue";

const hooks = vi.hoisted(() => ({ session: null as unknown }));

vi.mock("../identity/useIdentity", () => ({
  useCurrentSession: () => hooks.session,
}));

const flag = {
  id: "flag-1",
  voteId: "vote-1",
  memberId: "member-1",
  product: {
    id: "product-1",
    name: "Alpha launch",
    pitch: "A useful product",
    logoUrl: null,
    topics: ["Developer tools"],
  },
  signalCode: "account_velocity",
  createdAt: "2026-10-24T12:00:00Z",
  rawIpAddress: "198.51.100.25",
};

function staffSession(role: "reviewer" | "admin" = "reviewer") {
  return {
    data: {
      account_id: "private-reviewer-account",
      csrf_token: "private-csrf-token",
      role,
      suspended: false,
      verified: true,
    },
    isPending: false,
    isError: false,
  };
}

function renderQueue(client: {
  fetchPending: ReturnType<typeof vi.fn>;
  decide: ReturnType<typeof vi.fn>;
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return render(
    <VoteReviewQueue
      client={client as never}
      identityClient={{} as IdentityClient}
    />,
    { wrapper },
  );
}

beforeEach(() => {
  hooks.session = staffSession();
  vi.stubGlobal(
    "confirm",
    vi.fn(() => true),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("VoteReviewQueue", () => {
  it("denies non-reviewers without querying the protected queue", () => {
    hooks.session = {
      ...staffSession(),
      data: { ...staffSession().data, role: "member" },
    };
    const client = {
      fetchPending: vi.fn(),
      decide: vi.fn(),
    };

    renderQueue(client);

    expect(
      screen.getByRole("heading", { name: "Reviewer access required" }),
    ).toBeTruthy();
    expect(client.fetchPending).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("private-reviewer-account");
  });

  it("shows only permitted flag context without raw network identifiers", async () => {
    const client = {
      fetchPending: vi
        .fn()
        .mockResolvedValue({ items: [flag], nextCursor: null }),
      decide: vi.fn(),
    };

    renderQueue(client);

    expect(await screen.findByText("Alpha launch")).toBeTruthy();
    expect(screen.getByText("member-1")).toBeTruthy();
    expect(screen.getByText("vote-1")).toBeTruthy();
    expect(screen.getByText("Unusual voting frequency")).toBeTruthy();
    expect(document.body.textContent).not.toContain("198.51.100.25");
    expect(document.body.textContent).not.toContain("private-reviewer-account");
  });

  it("requires a reason and clears a flag without requiring invalidation confirmation", async () => {
    let decided = false;
    const client = {
      fetchPending: vi
        .fn()
        .mockImplementation(() =>
          Promise.resolve({ items: decided ? [] : [flag], nextCursor: null }),
        ),
      decide: vi.fn().mockImplementation(() => {
        decided = true;
        return Promise.resolve({
          id: "decision-1",
          flag_id: "flag-1",
          reviewer_account_id: "reviewer-1",
          outcome: "cleared",
          reason: "Reviewed the account history",
          created_at: "2026-10-24T12:30:00Z",
        });
      }),
    };

    renderQueue(client);
    const clear = await screen.findByRole("button", { name: "Clear flag" });
    expect(clear.hasAttribute("disabled")).toBe(true);
    fireEvent.change(screen.getByLabelText("Decision reason"), {
      target: { value: "Reviewed the account history" },
    });
    fireEvent.click(clear);

    await waitFor(() =>
      expect(client.decide).toHaveBeenCalledWith("flag-1", {
        outcome: "cleared",
        reason: "Reviewed the account history",
      }),
    );
    expect(window.confirm).not.toHaveBeenCalled();
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain(
      "Flag cleared; the vote remains counted.",
    );
    expect(
      await screen.findByRole("heading", {
        name: "No flagged votes need review",
      }),
    ).toBeTruthy();
  });

  it("requires explicit confirmation before invalidating a vote", async () => {
    const client = {
      fetchPending: vi
        .fn()
        .mockResolvedValue({ items: [flag], nextCursor: null }),
      decide: vi.fn().mockResolvedValue({ outcome: "invalidated" }),
    };
    vi.stubGlobal(
      "confirm",
      vi.fn(() => false),
    );

    renderQueue(client);
    fireEvent.change(await screen.findByLabelText("Decision reason"), {
      target: { value: "Confirmed coordinated abuse" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Invalidate vote" }));
    expect(window.confirm).toHaveBeenCalledOnce();
    expect(client.decide).not.toHaveBeenCalled();

    vi.mocked(window.confirm).mockReturnValueOnce(true);
    fireEvent.click(screen.getByRole("button", { name: "Invalidate vote" }));
    await waitFor(() =>
      expect(client.decide).toHaveBeenCalledWith("flag-1", {
        outcome: "invalidated",
        reason: "Confirmed coordinated abuse",
      }),
    );
  });

  it("shows a safe conflict message and retries the queue after a concurrent decision", async () => {
    const client = {
      fetchPending: vi
        .fn()
        .mockResolvedValue({ items: [flag], nextCursor: null }),
      decide: vi.fn().mockRejectedValue(new VoteReviewRequestError(409)),
    };

    renderQueue(client);
    fireEvent.change(await screen.findByLabelText("Decision reason"), {
      target: { value: "Reviewed the timeline" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Clear flag" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "This flag was already decided. Refresh the queue.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh queue" }));
    await waitFor(() => expect(client.fetchPending).toHaveBeenCalledTimes(2));
  });

  it("pages the queue and returns to the previous cursor", async () => {
    const client = {
      fetchPending: vi.fn((variables: { after?: string | null }) =>
        Promise.resolve(
          variables.after === "cursor-2"
            ? { items: [], nextCursor: null }
            : { items: [flag], nextCursor: "cursor-2" },
        ),
      ),
      decide: vi.fn(),
    };

    renderQueue(client);
    fireEvent.click(
      await screen.findByRole("button", { name: "Load more flagged votes" }),
    );
    await waitFor(() =>
      expect(client.fetchPending).toHaveBeenLastCalledWith({
        first: 20,
        after: "cursor-2",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    await waitFor(() =>
      expect(client.fetchPending).toHaveBeenLastCalledWith({
        first: 20,
        after: null,
      }),
    );
  });
});
