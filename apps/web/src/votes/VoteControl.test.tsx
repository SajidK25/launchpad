/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createIdentityClient, type IdentityClient } from "../identity/client";
import { VoteControl } from "./VoteControl";

const member = {
  account_id: "member-1",
  csrf_token: "csrf-token",
  role: "member",
  verified: true,
  suspended: false,
};

function createVoteResponse(active: boolean) {
  return {
    vote_id: "vote-1",
    product_id: "product-1",
    active,
    cast_at: "2026-10-25T00:00:00Z",
    replayed: false,
  };
}

function renderControl({
  session = member,
  voteResponses = [createVoteResponse(true)],
  viewerVoted = false,
  votingOpen = true,
  siteKey = "",
}: {
  session?: typeof member | null;
  voteResponses?: Array<
    Record<string, unknown> | { status: number; detail: string }
  >;
  viewerVoted?: boolean | null;
  votingOpen?: boolean;
  siteKey?: string;
} = {}) {
  let commandIndex = 0;
  const fetcher = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const path = String(input);
      if (path === "/api/v1/auth/session") {
        if (!session)
          return Response.json(
            { detail: "not authenticated" },
            { status: 401 },
          );
        return Response.json(session);
      }
      const result = voteResponses[commandIndex++] ?? createVoteResponse(true);
      if (
        "status" in result &&
        typeof result.status === "number" &&
        "detail" in result &&
        typeof result.detail === "string"
      )
        return Response.json(
          { detail: result.detail },
          { status: result.status },
        );
      return Response.json(result);
    },
  );
  vi.stubGlobal("fetch", fetcher);
  const identityClient = createIdentityClient(fetcher) as IdentityClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <VoteControl
        activeVoteCount={2}
        identityClient={identityClient}
        launchDate="2026-10-25"
        productId="product-1"
        siteKey={siteKey}
        viewerVoted={viewerVoted}
        votingOpen={votingOpen}
      />
    </QueryClientProvider>,
  );
  return { ...view, fetcher };
}

afterEach(() => {
  cleanup();
  delete window.turnstile;
  document.querySelector('script[data-launchpad-turnstile="true"]')?.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("VoteControl", () => {
  it("returns a guest to the same product through a safe sign-in path", async () => {
    renderControl({ session: null });
    const link = await screen.findByRole("link", { name: "Sign in to vote" });
    expect(link.getAttribute("href")).toBe(
      "/signin?returnTo=%2Flaunches%2Fproduct-1",
    );
    fireEvent.click(link);
    expect(window.location.pathname).toBe("/signin");
    expect(window.location.search).toBe("?returnTo=%2Flaunches%2Fproduct-1");
  });

  it("confirms a vote and withdrawal from server responses", async () => {
    const { fetcher } = renderControl({
      voteResponses: [createVoteResponse(true), createVoteResponse(false)],
    });
    const cast = await screen.findByRole("button", {
      name: "Vote for this launch",
    });
    fireEvent.click(cast);
    expect((await screen.findByRole("status")).textContent).toContain(
      "Your vote is recorded.",
    );
    const remove = await screen.findByRole("button", { name: "Remove vote" });
    fireEvent.click(remove);
    expect(await screen.findByText(/Your vote was removed/)).toBeTruthy();
    const commands = fetcher.mock.calls.filter(([input]) =>
      String(input).startsWith("/api/v1/votes"),
    );
    expect(commands).toHaveLength(2);
    expect(commands[0]?.[1]).toMatchObject({ method: "POST" });
    expect(commands[1]?.[1]).toMatchObject({ method: "DELETE" });
    expect(
      (commands[0]?.[1]?.headers as Record<string, string>)["Idempotency-Key"],
    ).not.toBe(
      (commands[1]?.[1]?.headers as Record<string, string>)["Idempotency-Key"],
    );
  });

  it("reveals Turnstile only after the server requests it and retries with the same command key", async () => {
    const tokenOptions: Array<{ callback: (token: string) => void }> = [];
    window.turnstile = {
      render: (_container, options) => {
        tokenOptions.push(options);
        return "widget-1";
      },
      remove: vi.fn(),
    };
    const { fetcher } = renderControl({
      siteKey: "public-site-key",
      voteResponses: [
        { status: 422, detail: "complete the security check and retry" },
        createVoteResponse(true),
      ],
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Vote for this launch" }),
    );
    expect(
      await screen.findByText(
        "Complete the security check to continue voting.",
      ),
    ).toBeTruthy();
    expect(tokenOptions).toHaveLength(1);
    act(() => tokenOptions[0]?.callback("turnstile-token"));
    fireEvent.click(screen.getByRole("button", { name: "Verify and vote" }));
    expect(await screen.findByText(/Your vote is recorded/)).toBeTruthy();

    const commands = fetcher.mock.calls.filter(
      ([input]) => String(input) === "/api/v1/votes",
    );
    expect(commands).toHaveLength(2);
    const firstHeaders = commands[0]?.[1]?.headers as Record<string, string>;
    const secondHeaders = commands[1]?.[1]?.headers as Record<string, string>;
    expect(secondHeaders["X-Turnstile-Token"]).toBe("turnstile-token");
    expect(secondHeaders["Idempotency-Key"]).toBe(
      firstHeaders["Idempotency-Key"],
    );
  });

  it("preserves confirmed state on a retryable failure and reuses the idempotency key", async () => {
    const { fetcher } = renderControl({
      voteResponses: [
        { status: 503, detail: "service temporarily unavailable" },
        createVoteResponse(true),
      ],
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Vote for this launch" }),
    );
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Your previous vote is unchanged",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry vote" }));
    expect(await screen.findByText(/Your vote is recorded/)).toBeTruthy();
    const commands = fetcher.mock.calls.filter(
      ([input]) => String(input) === "/api/v1/votes",
    );
    const keys = commands.map(
      ([, init]) =>
        (init?.headers as Record<string, string>)["Idempotency-Key"],
    );
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it("does not offer a vote on a closed launch or to an unverified member", async () => {
    const closed = renderControl({ votingOpen: false });
    expect(
      await screen.findByText("Voting is closed for this launch."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /vote/i })).toBeNull();
    closed.unmount();

    renderControl({ session: { ...member, verified: false } });
    expect(await screen.findByText(/Verify your email/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /vote/i })).toBeNull();

    cleanup();
    renderControl({ session: { ...member, suspended: true } });
    expect(
      await screen.findByText(/unavailable while your account is suspended/),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /vote/i })).toBeNull();
  });

  it("keeps the previous count and confirmed state after a self-vote rejection", async () => {
    renderControl({ voteResponses: [{ status: 403, detail: "not allowed" }] });
    fireEvent.click(
      await screen.findByRole("button", { name: "Vote for this launch" }),
    );

    expect((await screen.findByRole("alert")).textContent).toContain(
      "account or product",
    );
    expect(screen.getByText("2 votes")).toBeTruthy();
    expect(
      screen
        .getByRole("button", { name: "Retry vote" })
        .getAttribute("aria-pressed"),
    ).toBe("false");
  });
});
