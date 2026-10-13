import { useRef, useState, type FormEvent } from "react";
import type { ViewerProductQuery } from "@launchpad/contracts/src/graphql.generated";
import type { IdentityClient } from "../identity/client";
import { navigate } from "../identity/Screens";
import {
  ProductRequestError,
  type ProductClient,
  type ReviewDecisionInput,
  type ReviewDecisionResult,
} from "./client";
import {
  useApprovedReviews,
  useDecideReview,
  useReviewProduct,
  useReviewQueue,
} from "./useProducts";
import { formatBytes } from "./format";

type ProductDetail = NonNullable<ViewerProductQuery["viewerProduct"]>;

export function StaffReviewQueue({ client }: { client: ProductClient }) {
  const [cursors, setCursors] = useState<Array<string | null>>([null]);
  const after = cursors[cursors.length - 1] ?? null;
  const queue = useReviewQueue(client, 20, after);
  const items = queue.data?.items ?? [];

  return (
    <div className="staff-review-workspace">
      <section
        aria-labelledby="review-title"
        className="product-panel staff-review"
      >
        <a
          className="back-link-button"
          href="/products"
          onClick={linkTo("/products")}
        >
          ← Your products
        </a>
        <p className="eyebrow">Staff workspace</p>
        <div className="staff-review-heading">
          <div>
            <h1 id="review-title">Staff review queue</h1>
            <p className="product-intro">
              Pending submissions, oldest arrival first. Current product details
              are shown when you open an entry.
            </p>
          </div>
          <button
            className="secondary-button"
            disabled={queue.isFetching}
            onClick={() => void queue.refetch()}
            type="button"
          >
            {queue.isFetching ? "Refreshing…" : "Refresh queue"}
          </button>
        </div>
        {queue.isPending ? (
          <p role="status">Loading pending submissions…</p>
        ) : null}
        {queue.isError ? (
          <p className="product-alert" role="alert">
            The staff queue is unavailable. Try refreshing.
          </p>
        ) : null}
        {queue.data && items.length === 0 ? (
          <div className="product-empty">
            <h2>No pending submissions</h2>
            <p>New submissions will appear here in arrival order.</p>
          </div>
        ) : null}
        {items.length > 0 ? (
          <ol
            className="staff-queue-list"
            aria-label="Pending submissions, oldest first"
          >
            {items.map((item) => (
              <li key={item.submission.id}>
                <a
                  className="staff-queue-card"
                  href={`/products/review/${item.product.id}`}
                  onClick={linkTo(`/products/review/${item.product.id}`)}
                >
                  <span className="staff-queue-title">
                    {item.product.name?.trim() || "Untitled product"}
                  </span>
                  <span className="staff-queue-pitch">
                    {item.product.pitch?.trim() || "No one-line pitch"}
                  </span>
                  <span>
                    Submitted {formatReviewDate(item.submission.submittedAt)}
                  </span>
                  <span>Version {item.submission.productVersion}</span>
                  <span className="staff-queue-flags">
                    {item.possibleDuplicate ? (
                      <span className="staff-flag staff-flag-warning">
                        Possible duplicate website
                      </span>
                    ) : null}
                    {item.founderSuspended ? (
                      <span className="staff-flag staff-flag-danger">
                        Founder suspended
                      </span>
                    ) : null}
                  </span>
                  <span className="staff-queue-open">
                    Open current submission →
                  </span>
                </a>
              </li>
            ))}
          </ol>
        ) : null}
        <nav aria-label="Queue pages" className="staff-queue-pagination">
          <button
            className="secondary-button"
            disabled={cursors.length <= 1 || queue.isFetching}
            onClick={() => setCursors((current) => current.slice(0, -1))}
            type="button"
          >
            Previous page
          </button>
          <span>Page {cursors.length}</span>
          <button
            className="secondary-button"
            disabled={!queue.data?.nextCursor || queue.isFetching}
            onClick={() => {
              if (queue.data?.nextCursor)
                setCursors((current) => [...current, queue.data!.nextCursor]);
            }}
            type="button"
          >
            Next page
          </button>
        </nav>
      </section>
      <StaffApprovedReviewList client={client} />
    </div>
  );
}

export function StaffApprovedReviewList({ client }: { client: ProductClient }) {
  const [cursors, setCursors] = useState<Array<string | null>>([null]);
  const after = cursors[cursors.length - 1] ?? null;
  const approved = useApprovedReviews(client, 20, after);
  const items = approved.data?.items ?? [];

  return (
    <section
      aria-labelledby="approved-reviews-title"
      className="product-panel staff-review"
    >
      <h2 id="approved-reviews-title">
        Approved products needing a second look
      </h2>
      <p className="product-intro">
        Approved products remain private. Open one to request a correction if
        needed.
      </p>
      {approved.isPending ? (
        <p role="status">Loading approved products…</p>
      ) : null}
      {approved.isError ? (
        <p role="alert" className="product-alert">
          Approved products are unavailable. Refresh the page to try again.
        </p>
      ) : null}
      {approved.data && items.length === 0 ? (
        <p className="product-muted">No approved products need review.</p>
      ) : null}
      {items.length ? (
        <ol aria-label="Approved products" className="staff-queue-list">
          {items.map((item) => (
            <li key={item.product.id}>
              <a
                className="staff-queue-card"
                href={`/products/review/${item.product.id}`}
                onClick={linkTo(`/products/review/${item.product.id}`)}
              >
                <span className="staff-queue-title">
                  {item.product.name?.trim() || "Untitled product"}
                </span>
                <span className="staff-queue-pitch">
                  {item.product.pitch?.trim() || "No one-line pitch"}
                </span>
                <span>Approved {formatReviewDate(item.approvedAt)}</span>
                <span className="staff-queue-open">
                  Open approved product →
                </span>
              </a>
            </li>
          ))}
        </ol>
      ) : null}
      <nav
        aria-label="Approved product pages"
        className="staff-queue-pagination"
      >
        <button
          className="secondary-button"
          disabled={cursors.length <= 1 || approved.isFetching}
          onClick={() => setCursors((current) => current.slice(0, -1))}
          type="button"
        >
          Previous approved page
        </button>
        <span>Page {cursors.length}</span>
        <button
          className="secondary-button"
          disabled={!approved.data?.nextCursor || approved.isFetching}
          onClick={() => {
            if (approved.data?.nextCursor)
              setCursors((current) => [...current, approved.data!.nextCursor]);
          }}
          type="button"
        >
          Next approved page
        </button>
      </nav>
    </section>
  );
}

export function StaffReviewDetail({
  client,
  productId,
}: {
  client: ProductClient;
  productId: string;
}) {
  const review = useReviewProduct(client, productId);
  const decide = useDecideReview(client, productId);
  const data = review.data;
  const product = data?.product;
  return (
    <section
      aria-labelledby="review-detail-title"
      className="product-panel staff-review staff-review-detail"
    >
      <a
        className="back-link-button"
        href="/products/review"
        onClick={linkTo("/products/review")}
      >
        ← Staff review queue
      </a>
      {review.isPending ? (
        <p role="status">Loading current submission…</p>
      ) : null}
      {review.isError ? (
        <p className="product-alert" role="alert">
          Current submission details are unavailable. Refresh the page to try
          again.
        </p>
      ) : null}
      {review.data === null ? (
        <div className="product-empty">
          <h1 id="review-detail-title">Submission no longer pending</h1>
          <p>
            This item may have been withdrawn. It is no longer in the queue.
          </p>
          <button
            className="secondary-button"
            onClick={() => void review.refetch()}
            type="button"
          >
            Refresh submission
          </button>
        </div>
      ) : null}
      {data && product ? (
        <>
          <p className="eyebrow">
            {product.summary.status === "approved"
              ? "Approved private product"
              : "Current pending submission"}
          </p>
          <div className="staff-review-heading">
            <div>
              <h1 id="review-detail-title">
                {product.summary.name?.trim() || "Untitled product"}
              </h1>
              <p className="product-intro">
                {product.summary.pitch || "No one-line pitch"}
              </p>
            </div>
            <button
              className="secondary-button"
              disabled={review.isFetching}
              onClick={() => void review.refetch()}
              type="button"
            >
              {review.isFetching ? "Refreshing…" : "Refresh current details"}
            </button>
          </div>
          <div
            className="staff-review-flags"
            aria-label="Staff-only submission flags"
          >
            {data.founderSuspended ? (
              <p className="staff-flag staff-flag-danger" role="status">
                Founder account suspended
              </p>
            ) : null}
            {data.possibleDuplicate ? (
              <p className="staff-flag staff-flag-warning" role="status">
                Possible duplicate website
              </p>
            ) : null}
            {!data.founderSuspended && !data.possibleDuplicate ? (
              <p className="staff-flag staff-flag-neutral">No staff flags</p>
            ) : null}
          </div>
          <dl className="staff-review-metadata">
            <div>
              <dt>Submission ID</dt>
              <dd>{data.submission.id}</dd>
            </div>
            <div>
              <dt>Submitted</dt>
              <dd>{formatReviewDate(data.submission.submittedAt)}</dd>
            </div>
            <div>
              <dt>Current product version</dt>
              <dd>{product.summary.version}</dd>
            </div>
            <div>
              <dt>Submission version</dt>
              <dd>{data.submission.productVersion}</dd>
            </div>
          </dl>
          <section
            aria-labelledby="review-description-title"
            className="staff-review-section"
          >
            <h2 id="review-description-title">Description</h2>
            <p>{product.description || "No description provided."}</p>
          </section>
          <section
            aria-labelledby="review-website-title"
            className="staff-review-section"
          >
            <h2 id="review-website-title">Product website</h2>
            {product.websiteUrl ? (
              <a href={product.websiteUrl} rel="noreferrer" target="_blank">
                {product.websiteUrl}
              </a>
            ) : (
              <p>No website provided.</p>
            )}
          </section>
          <section
            aria-labelledby="review-topics-title"
            className="staff-review-section"
          >
            <h2 id="review-topics-title">Topics</h2>
            <ul className="staff-topic-list">
              {product.topics.map((topic) => (
                <li key={topic.id}>{topic.displayName}</li>
              ))}
            </ul>
          </section>
          <section
            aria-labelledby="review-media-title"
            className="staff-review-section"
          >
            <h2 id="review-media-title">Private product media</h2>
            {product.assets.length ? (
              <div className="staff-media-grid">
                {product.assets.map((asset) => (
                  <figure key={asset.id}>
                    <img
                      alt={
                        asset.kind === "logo"
                          ? "Product logo"
                          : "Product screenshot"
                      }
                      className="staff-media-preview"
                      loading="lazy"
                      src={asset.url}
                    />
                    <figcaption>
                      {asset.kind === "logo" ? "Logo" : "Screenshot"} ·{" "}
                      {asset.mediaType} · {formatBytes(asset.byteCount)}
                    </figcaption>
                  </figure>
                ))}
              </div>
            ) : (
              <p>No media is attached to this submission.</p>
            )}
          </section>
          {product.summary.status === "submitted" ||
          product.summary.status === "approved" ? (
            <StaffDecisionPanel
              currentStatus={product.summary.status}
              isPending={decide.isPending}
              onDecide={decide.mutateAsync}
              productVersion={product.summary.version}
              submissionId={data.submission.id}
            />
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function StaffDecisionPanel({
  currentStatus,
  isPending,
  onDecide,
  productVersion,
  submissionId,
}: {
  currentStatus: string;
  isPending: boolean;
  onDecide: (variables: {
    payload: ReviewDecisionInput;
    idempotencyKey: string;
  }) => Promise<ReviewDecisionResult>;
  productVersion: number;
  submissionId: string;
}) {
  const isApproved = currentStatus === "approved";
  const [outcome, setOutcome] = useState<ReviewDecisionInput["outcome"]>(
    isApproved ? "changes_requested" : "approved",
  );
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const previousRequest = useRef<{
    signature: string;
    idempotencyKey: string;
  } | null>(null);

  async function recordDecision(event: FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    const trimmedFeedback = feedback.trim();
    if (outcome !== "approved" && !trimmedFeedback) {
      setError(
        "Add an explanation for the founder before recording this decision.",
      );
      return;
    }
    if (outcome !== "approved" && trimmedFeedback.length > 2000) {
      setError("Feedback must be 2,000 characters or fewer.");
      return;
    }

    const payload: ReviewDecisionInput = {
      submission_id: submissionId,
      expected_version: productVersion,
      outcome,
      ...(outcome === "approved" ? {} : { feedback: trimmedFeedback }),
    };
    const signature = JSON.stringify(payload);
    if (previousRequest.current?.signature !== signature) {
      previousRequest.current = {
        signature,
        idempotencyKey: createReviewIdempotencyKey(),
      };
    }
    try {
      const result = await onDecide({
        payload,
        idempotencyKey: previousRequest.current!.idempotencyKey,
      });
      setNotice(
        `Decision recorded. Product status: ${productStatusLabel(result.status)}.`,
      );
    } catch (caught) {
      if (caught instanceof ProductRequestError && caught.status === 409) {
        setError(
          "This product changed after you opened it. Current details were refreshed; review them before retrying.",
        );
      } else {
        setError(
          "The decision could not be recorded. Your review details are unchanged.",
        );
      }
    }
  }

  return (
    <section
      aria-labelledby="review-decision-title"
      className="staff-review-section staff-decision-panel"
    >
      <h2 id="review-decision-title">Review outcome</h2>
      <form noValidate onSubmit={(event) => void recordDecision(event)}>
        <label className="product-field" htmlFor="review-outcome">
          Decision
          <select
            id="review-outcome"
            onChange={(event) =>
              setOutcome(event.target.value as ReviewDecisionInput["outcome"])
            }
            value={outcome}
          >
            {isApproved ? (
              <option value="changes_requested">Request changes</option>
            ) : (
              <>
                <option value="approved">Approve</option>
                <option value="rejected">Reject</option>
                <option value="changes_requested">Request changes</option>
              </>
            )}
          </select>
        </label>
        {outcome !== "approved" ? (
          <label className="product-field" htmlFor="review-feedback">
            Feedback for the founder
            <textarea
              aria-describedby="review-feedback-help"
              id="review-feedback"
              maxLength={2001}
              onChange={(event) => setFeedback(event.target.value)}
              rows={5}
              value={feedback}
            />
            <small id="review-feedback-help">
              Required for this decision; up to 2,000 characters after trimming.{" "}
              {feedback.length}/2,000
            </small>
          </label>
        ) : null}
        {error ? (
          <p className="product-alert" role="alert">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p className="product-notice" role="status">
            {notice}
          </p>
        ) : null}
        <button className="primary-button" disabled={isPending} type="submit">
          {isPending ? "Recording decision…" : "Record review decision"}
        </button>
      </form>
    </section>
  );
}

export function canReviewQueue(
  session: Awaited<ReturnType<IdentityClient["currentSession"]>>,
): boolean {
  return (
    session.verified &&
    !session.suspended &&
    (session.role === "reviewer" || session.role === "admin")
  );
}

function formatReviewDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

export function productStatusLabel(status: string): string {
  switch (status) {
    case "submitted":
      return "In review";
    case "changes_requested":
      return "Changes requested";
    case "approved":
      return "Approved · private";
    case "rejected":
      return "Rejected";
    case "draft":
    default:
      return "Private draft";
  }
}

function linkTo(path: string) {
  return (event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    navigate(path);
  };
}

function createReviewIdempotencyKey(): string {
  if (typeof globalThis.crypto?.randomUUID === "function")
    return globalThis.crypto.randomUUID();
  return `review-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
