/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IdentityClient } from "../identity/client";
import { CommentRequestError } from "./client";
import { CommentsSection } from "./CommentsSection";

const mocks = vi.hoisted(() => ({
  session: { data: null, isPending: false, isError: true } as Record<
    string,
    unknown
  >,
  profile: {
    accountId: "account-1",
    displayName: "Ada Lovelace",
    bio: "",
    links: [],
    photoUrl: "/ada.png",
    visibility: "private",
    version: 1,
  } as {
    accountId: string;
    displayName: string;
    bio: string;
    links: string[];
    photoUrl: string | null;
    visibility: string;
    version: number;
  },
  pages: [] as Array<Record<string, unknown>>,
  createComment: vi.fn(),
  createReply: vi.fn(),
  fetchNextPage: vi.fn(),
  live: {
    connected: true,
    closed: false,
    newActivityCount: 0,
    showNewActivity: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock("../identity/useIdentity", () => ({
  useCurrentSession: () => mocks.session,
}));
vi.mock("../profiles/client", () => ({
  createProfileClient: () => ({
    fetchViewerProfile: vi
      .fn()
      .mockImplementation(() => Promise.resolve(mocks.profile)),
  }),
}));
vi.mock("./useComments", async () => {
  const actual =
    await vi.importActual<typeof import("./useComments")>("./useComments");
  return {
    ...actual,
    useDiscussion: () => ({
      data: { pages: mocks.pages },
      isPending: false,
      isError: false,
      hasNextPage: true,
      isFetchingNextPage: false,
      fetchNextPage: mocks.fetchNextPage,
    }),
    useCommentReplies: () => ({
      data: { pages: [] },
      isFetchingNextPage: false,
      hasNextPage: false,
      fetchNextPage: vi.fn(),
    }),
    useCreateComment: () => ({
      isPending: false,
      mutateAsync: mocks.createComment,
    }),
    useCreateReply: () => ({
      isPending: false,
      mutateAsync: mocks.createReply,
    }),
  };
});
vi.mock("./useCommentsLive", () => ({ useCommentsLive: () => mocks.live }));

const identity = {
  getCsrfToken: vi.fn().mockReturnValue("csrf"),
  ensureSession: vi.fn().mockResolvedValue({}),
} as unknown as IdentityClient;

const author = {
  accountId: "author-1",
  displayName: "Grace Hopper",
  avatarUrl: "/grace.png",
  publicProfileUrl: "/people/author-1",
};

function thread(overrides: Record<string, unknown> = {}) {
  return {
    id: "root-1",
    productId: "product-1",
    parentId: null,
    body: "<script>alert('plain text')</script>",
    createdAt: "2026-11-20T08:00:00Z",
    author,
    replyCount: 2,
    replies: [
      {
        id: "reply-1",
        productId: "product-1",
        parentId: "root-1",
        body: "First",
        createdAt: "2026-11-20T08:01:00Z",
        author,
      },
      {
        id: "reply-2",
        productId: "product-1",
        parentId: "root-1",
        body: "Second",
        createdAt: "2026-11-20T08:02:00Z",
        author,
      },
    ],
    ...overrides,
  };
}

function renderComments() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CommentsSection identityClient={identity} productId="product-1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.session = { data: null, isPending: false, isError: true };
  mocks.pages = [{ items: [thread()], nextCursor: "older" }];
  mocks.createComment.mockReset();
  mocks.createReply.mockReset();
  mocks.fetchNextPage.mockReset();
  mocks.live.connected = true;
  mocks.live.closed = false;
  mocks.live.newActivityCount = 0;
  mocks.live.showNewActivity.mockClear();
  vi.stubGlobal("crypto", { randomUUID: () => "attempt-key" });
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("CommentsSection", () => {
  it("renders bounded public discussion safely and keeps reply order", () => {
    renderComments();
    expect(screen.getByRole("heading", { name: "Discussion" })).toBeTruthy();
    expect(
      screen.getByText("<script>alert('plain text')</script>"),
    ).toBeTruthy();
    expect(document.querySelector("script")).toBeNull();
    const replies = screen.getByRole("list", {
      name: "Replies to Grace Hopper",
    });
    expect(replies.textContent?.indexOf("First")).toBeLessThan(
      replies.textContent?.indexOf("Second") ?? 0,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Load older comments" }),
    );
    expect(mocks.fetchNextPage).toHaveBeenCalledOnce();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeTruthy();
  });

  it.each([
    [{ role: "member", verified: false, suspended: false }, "Verify email"],
    [{ role: "member", verified: true, suspended: true }, "access is paused"],
    [{ role: "reviewer", verified: true, suspended: false }, "Staff accounts"],
  ])("keeps restricted accounts read-only", async (state, copy) => {
    mocks.session = {
      data: { account_id: "account-1", csrf_token: "csrf", ...state },
      isPending: false,
      isError: false,
    };
    renderComments();
    expect(await screen.findByText(new RegExp(copy, "i"))).toBeTruthy();
    expect(
      screen.queryByRole("textbox", { name: "Add to the discussion" }),
    ).toBeNull();
  });

  it("directs incomplete members to their profile", async () => {
    mocks.session = {
      data: {
        account_id: "account-1",
        csrf_token: "csrf",
        role: "member",
        verified: true,
        suspended: false,
      },
      isPending: false,
      isError: false,
    };
    mocks.profile = { ...mocks.profile, photoUrl: null };
    renderComments();
    expect(
      await screen.findByRole("link", { name: "Complete profile" }),
    ).toBeTruthy();
  });

  it("shows a confirmed comment immediately and clears only successful drafts", async () => {
    mocks.session = {
      data: {
        account_id: "account-1",
        csrf_token: "csrf",
        role: "member",
        verified: true,
        suspended: false,
      },
      isPending: false,
      isError: false,
    };
    mocks.profile = { ...mocks.profile, photoUrl: "/ada.png" };
    mocks.createComment.mockResolvedValue({
      id: "confirmed-1",
      product_id: "product-1",
      parent_id: null,
      body: "Confirmed contribution",
      created_at: "2026-11-20T09:00:00Z",
      replayed: false,
    });
    renderComments();
    const input = await screen.findByRole("textbox", {
      name: "Add to the discussion",
    });
    fireEvent.change(input, { target: { value: "Confirmed contribution" } });
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByText("Confirmed contribution")).toBeTruthy();
    expect((input as HTMLTextAreaElement).value).toBe("");
  });

  it("retains and focuses a failed draft error", async () => {
    mocks.session = {
      data: {
        account_id: "account-1",
        csrf_token: "csrf",
        role: "member",
        verified: true,
        suspended: false,
      },
      isPending: false,
      isError: false,
    };
    mocks.profile = { ...mocks.profile, photoUrl: "/ada.png" };
    mocks.createComment.mockRejectedValue(
      new CommentRequestError(429, "limited", "try later", 60),
    );
    renderComments();
    const input = await screen.findByRole("textbox", {
      name: "Add to the discussion",
    });
    fireEvent.change(input, { target: { value: "Keep this draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    const alert = await screen.findByRole("alert");
    expect((input as HTMLTextAreaElement).value).toBe("Keep this draft");
    expect(alert.textContent).toContain("draft is saved");
    await waitFor(() => expect(document.activeElement).toBe(alert));
  });

  it("reveals queued activity only on request", async () => {
    mocks.live.newActivityCount = 2;
    renderComments();
    fireEvent.click(screen.getByRole("button", { name: "2 new comments" }));
    await waitFor(() =>
      expect(mocks.live.showNewActivity).toHaveBeenCalledOnce(),
    );
    expect(document.activeElement).toBe(
      screen.getByRole("heading", { name: "Discussion" }),
    );
  });
});
