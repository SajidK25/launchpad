import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { components } from "@launchpad/contracts";
import {
  PENDING_VOTE_REVIEWS_QUERY,
  type PendingVoteReviewsQuery,
  type PendingVoteReviewsQueryVariables,
} from "@launchpad/contracts/src/graphql.generated";
import type { IdentityClient } from "../identity/client";
import { useCurrentSession } from "../identity/useIdentity";
import { LoadingState, UnavailableState } from "../ui/Primitives";
import "./votes.css";

type PendingPage = PendingVoteReviewsQuery["pendingVoteReviews"];
type Decision = components["schemas"]["VoteReviewDecisionInput"];
type DecisionResult = components["schemas"]["VoteReviewDecisionResponse"];
type Fetcher = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export class VoteReviewRequestError extends Error {
  constructor(readonly status: number) {
    super("Vote review request failed.");
    this.name = "VoteReviewRequestError";
  }
}

export function createVoteReviewClient(
  identity: Pick<IdentityClient, "ensureSession" | "getCsrfToken">,
  fetcher: Fetcher = globalThis.fetch.bind(globalThis),
) {
  return {
    fetchPending: async (
      variables: PendingVoteReviewsQueryVariables,
    ): Promise<PendingPage> => {
      await identity.ensureSession();
      const response = await fetcher("/api/v1/graphql", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: PENDING_VOTE_REVIEWS_QUERY,
          variables,
        }),
      });
      const value: unknown = await response.json().catch(() => null);
      if (!response.ok || !isRecord(value) || !isRecord(value.data))
        throw new VoteReviewRequestError(response.status);
      if (Array.isArray(value.errors) && value.errors.length > 0)
        throw new VoteReviewRequestError(403);
      const page = value.data.pendingVoteReviews;
      if (!isPendingPage(page)) throw new VoteReviewRequestError(502);
      return page;
    },
    decide: async (
      flagId: string,
      decision: Decision,
    ): Promise<DecisionResult> => {
      await identity.ensureSession();
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      const csrfToken = identity.getCsrfToken();
      if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
      const response = await fetcher(
        `/api/v1/votes/reviews/${encodeURIComponent(flagId)}/decision`,
        {
          method: "POST",
          credentials: "include",
          headers,
          body: JSON.stringify(decision),
        },
      );
      const value: unknown = await response.json().catch(() => null);
      if (!response.ok || !isDecisionResult(value))
        throw new VoteReviewRequestError(response.status);
      return value;
    },
  };
}

type VoteReviewClient = ReturnType<typeof createVoteReviewClient>;

export function VoteReviewQueue({
  identityClient,
  client = createVoteReviewClient(identityClient),
}: {
  identityClient: IdentityClient;
  client?: VoteReviewClient;
}) {
  const session = useCurrentSession(identityClient);
  const [cursors, setCursors] = useState<Array<string | null>>([null]);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const queryClient = useQueryClient();
  const after = cursors[cursors.length - 1] ?? null;
  const authorized = Boolean(
    session.data?.verified &&
      !session.data.suspended &&
      (session.data.role === "reviewer" || session.data.role === "admin"),
  );
  const queue = useQuery({
    queryKey: ["votes", "review-queue", after],
    queryFn: () => client.fetchPending({ first: 20, after }),
    enabled: authorized,
  });
  const decision = useMutation({
    mutationFn: ({ flagId, payload }: { flagId: string; payload: Decision }) =>
      client.decide(flagId, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["votes", "review-queue"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["launches", "daily-ranking"],
      });
    },
  });

  if (session.isPending)
    return (
      <LoadingState
        title="Checking reviewer access"
        description="We’re confirming your account permissions."
      />
    );
  if (session.isError)
    return (
      <UnavailableState
        title="Review queue unavailable"
        description="We couldn’t confirm reviewer access. Refresh or sign in again."
      />
    );
  if (!authorized)
    return (
      <UnavailableState
        title="Reviewer access required"
        description="This queue is available only to verified, active reviewers."
        action={
          <a className="ui-action ui-action--secondary" href="/">
            Return to Launchpad
          </a>
        }
      />
    );

  const items = queue.data?.items ?? [];

  function submit(flagId: string, outcome: Decision["outcome"]) {
    const reason = reasons[flagId]?.trim() ?? "";
    if (!reason || reason.length > 2000) return;
    if (
      outcome === "invalidated" &&
      !window.confirm(
        "Invalidate this vote? The action will be recorded in the audit history.",
      )
    )
      return;
    decision.mutate({ flagId, payload: { outcome, reason } });
  }

  return (
    <section aria-labelledby="vote-review-title" className="vote-review-page">
      <header className="vote-review-header">
        <p className="vote-review-eyebrow">Staff workspace</p>
        <h1 id="vote-review-title">Suspicious vote review</h1>
        <p>
          Review flagged activity. A flag does not change its vote until you
          explicitly decide it.
        </p>
        <button
          className="ui-action ui-action--secondary"
          disabled={queue.isFetching}
          onClick={() => void queue.refetch()}
          type="button"
        >
          {queue.isFetching ? "Refreshing…" : "Refresh queue"}
        </button>
      </header>
      {queue.isPending ? <p role="status">Loading flagged votes…</p> : null}
      {queue.isError ? (
        <div className="vote-review-error" role="alert">
          <p>
            {queue.error instanceof VoteReviewRequestError &&
            [401, 403].includes(queue.error.status)
              ? "Reviewer access could not be confirmed. Sign in with an active reviewer account."
              : "The flagged-vote queue could not be loaded. Try again."}
          </p>
          <button
            className="ui-action ui-action--secondary"
            onClick={() => void queue.refetch()}
            type="button"
          >
            Retry
          </button>
        </div>
      ) : null}
      {decision.isError ? (
        <p className="vote-review-error" role="alert">
          {decision.error instanceof VoteReviewRequestError &&
          decision.error.status === 409
            ? "This flag was already decided. Refresh the queue."
            : "The decision could not be saved. Refresh and try again."}
        </p>
      ) : null}
      {decision.isSuccess ? (
        <p className="vote-review-success" role="status">
          {decision.data.outcome === "cleared"
            ? "Flag cleared; the vote remains counted."
            : "Vote invalidated; live ranking is refreshing."}{" "}
          Decision recorded for reviewer {decision.data.reviewer_account_id} at{" "}
          {formatFlagDate(decision.data.created_at)}.
        </p>
      ) : null}
      {queue.data && items.length === 0 ? (
        <div className="vote-review-empty">
          <h2>No flagged votes need review</h2>
          <p>
            New suspicious activity will appear here for an explicit decision.
          </p>
        </div>
      ) : null}
      {items.length > 0 ? (
        <ol
          aria-label="Pending suspicious vote flags"
          className="vote-review-list"
        >
          {items.map((item) => {
            const reason = reasons[item.id] ?? "";
            const busy = decision.isPending;
            return (
              <li className="vote-review-card" key={item.id}>
                <div className="vote-review-card-heading">
                  <div>
                    <p className="vote-review-eyebrow">Flag {item.id}</p>
                    <h2>{item.product.name || "Untitled product"}</h2>
                    <p>{item.product.pitch}</p>
                  </div>
                  {item.product.logoUrl ? (
                    <img
                      alt=""
                      className="vote-review-logo"
                      src={item.product.logoUrl}
                    />
                  ) : null}
                </div>
                <dl className="vote-review-context">
                  <div>
                    <dt>Member account</dt>
                    <dd>{item.memberId}</dd>
                  </div>
                  <div>
                    <dt>Vote</dt>
                    <dd>{item.voteId}</dd>
                  </div>
                  <div>
                    <dt>Signal category</dt>
                    <dd>{signalLabel(item.signalCode)}</dd>
                  </div>
                  <div>
                    <dt>Flagged</dt>
                    <dd>{formatFlagDate(item.createdAt)}</dd>
                  </div>
                  <div>
                    <dt>Topics</dt>
                    <dd>{item.product.topics.join(", ") || "None"}</dd>
                  </div>
                </dl>
                <label htmlFor={`vote-review-reason-${item.id}`}>
                  Decision reason
                </label>
                <textarea
                  id={`vote-review-reason-${item.id}`}
                  maxLength={2000}
                  onChange={(event) =>
                    setReasons((current) => ({
                      ...current,
                      [item.id]: event.target.value,
                    }))
                  }
                  required
                  rows={3}
                  value={reason}
                />
                <div className="vote-review-actions">
                  <button
                    className="ui-action ui-action--secondary"
                    disabled={busy || reason.trim().length === 0}
                    onClick={() => submit(item.id, "cleared")}
                    type="button"
                  >
                    Clear flag
                  </button>
                  <button
                    className="ui-action ui-action--danger"
                    disabled={busy || reason.trim().length === 0}
                    onClick={() => submit(item.id, "invalidated")}
                    type="button"
                  >
                    Invalidate vote
                  </button>
                </div>
              </li>
            );
          })}
        </ol>
      ) : null}
      {queue.data?.nextCursor ? (
        <button
          className="ui-action ui-action--secondary"
          disabled={queue.isFetching}
          onClick={() =>
            setCursors((current) => [...current, queue.data!.nextCursor])
          }
          type="button"
        >
          Load more flagged votes
        </button>
      ) : null}
      {cursors.length > 1 ? (
        <button
          className="ui-action ui-action--secondary"
          onClick={() => setCursors((current) => current.slice(0, -1))}
          type="button"
        >
          Previous page
        </button>
      ) : null}
    </section>
  );
}

function signalLabel(code: string): string {
  const labels: Record<string, string> = {
    account_velocity: "Unusual voting frequency",
    velocity_threshold: "Unusual voting frequency",
    velocity: "Unusual voting frequency",
    repeated_identity: "Repeated identity signal",
    risk_threshold: "Elevated risk score",
  };
  return labels[code] ?? "Automated risk signal";
}

function formatFlagDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "UTC",
      }).format(date) + " UTC";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isPendingPage(value: unknown): value is PendingPage {
  return (
    isRecord(value) &&
    Array.isArray(value.items) &&
    value.items.every(isPendingEntry) &&
    (value.nextCursor === null || typeof value.nextCursor === "string")
  );
}

function isPendingEntry(value: unknown): value is PendingPage["items"][number] {
  if (!isRecord(value) || !isRecord(value.product)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.voteId === "string" &&
    typeof value.memberId === "string" &&
    typeof value.signalCode === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.product.id === "string" &&
    typeof value.product.name === "string" &&
    typeof value.product.pitch === "string" &&
    (value.product.logoUrl === null ||
      typeof value.product.logoUrl === "string") &&
    Array.isArray(value.product.topics) &&
    value.product.topics.every((topic) => typeof topic === "string")
  );
}

function isDecisionResult(value: unknown): value is DecisionResult {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.flag_id === "string" &&
    typeof value.reviewer_account_id === "string" &&
    typeof value.reason === "string" &&
    typeof value.created_at === "string" &&
    (value.outcome === "cleared" || value.outcome === "invalidated")
  );
}
