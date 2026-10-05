import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import type { ViewerProductQuery } from "@launchpad/contracts/src/graphql.generated";
import { useCurrentSession, useLogout } from "../identity/useIdentity";
import type { IdentityClient } from "../identity/client";
import { navigate } from "../identity/Screens";
import {
  ProductRequestError,
  type ProductClient,
  type ReviewDecisionInput,
  type ReviewDecisionResult,
} from "./client";
import {
  useAttachProductAssets,
  useApprovedReviews,
  useCreateDraft,
  useDecideReview,
  useDeleteProductDraft,
  useProductAutosave,
  useReviewProduct,
  useReviewQueue,
  useSubmitProduct,
  useTopicChoices,
  useViewerProduct,
  useViewerProducts,
  useWithdrawProduct,
  type ProductDraftValues,
} from "./useProducts";

type ProductDetail = NonNullable<ViewerProductQuery["viewerProduct"]>;
type AttachedAsset = ProductDetail["assets"][number];
type LocalAsset = {
  id: string;
  kind: "logo" | "screenshot";
  mediaType: string;
  byteCount: number;
  previewUrl: string;
  fileName: string;
};
type Selection = { logo: string; screenshots: string[] };

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

export function ProductRoutes({
  client,
  identityClient,
  path,
}: {
  client: ProductClient;
  identityClient: IdentityClient;
  path: string;
}) {
  const session = useCurrentSession(identityClient);
  const reviewRoute = path.match(/^\/products\/review(?:\/([^/]+))?\/?$/);
  const route = path.match(/^\/products(?:\/([^/]+))?\/?$/);
  const workspaceLabel = reviewRoute ? "Staff workspace" : "Founder workspace";

  if (!route && !reviewRoute)
    return (
      <ProductFrame
        identityClient={identityClient}
        workspaceLabel={workspaceLabel}
      >
        <p role="alert">That product workspace page is unavailable.</p>
        <button
          className="secondary-button"
          onClick={() => navigate("/products")}
          type="button"
        >
          Your products
        </button>
      </ProductFrame>
    );
  if (session.isPending)
    return (
      <ProductFrame
        identityClient={identityClient}
        workspaceLabel={workspaceLabel}
      >
        <p role="status">Checking your account…</p>
      </ProductFrame>
    );
  if (session.isError || !session.data)
    return (
      <ProductFrame
        identityClient={identityClient}
        workspaceLabel={workspaceLabel}
      >
        <h1>Your products</h1>
        <p role="alert">Sign in to view or edit your private product drafts.</p>
        <button
          className="primary-button"
          onClick={() => navigate("/signin")}
          type="button"
        >
          Sign in
        </button>
      </ProductFrame>
    );

  return (
    <ProductFrame
      identityClient={identityClient}
      workspaceLabel={workspaceLabel}
    >
      {reviewRoute ? (
        canReviewQueue(session.data) ? (
          reviewRoute[1] ? (
            <StaffReviewDetail client={client} productId={reviewRoute[1]} />
          ) : (
            <StaffReviewQueue client={client} />
          )
        ) : (
          <section aria-labelledby="review-title" className="product-panel">
            <p className="eyebrow">Staff workspace</p>
            <h1 id="review-title">Staff review queue</h1>
            <p role="alert" className="product-alert">
              This queue is not available for your account.
            </p>
            <a href="/products" onClick={linkTo("/products")}>
              Back to your products
            </a>
          </section>
        )
      ) : route?.[1] ? (
        <ProductEditor
          client={client}
          identityClient={identityClient}
          productId={route[1]}
          session={session.data}
        />
      ) : (
        <ProductHome client={client} session={session.data} />
      )}
    </ProductFrame>
  );
}

function ProductFrame({
  identityClient,
  workspaceLabel,
  children,
}: {
  identityClient: IdentityClient;
  workspaceLabel: string;
  children: React.ReactNode;
}) {
  const logout = useLogout(identityClient);
  const [error, setError] = useState("");
  async function signOut() {
    setError("");
    try {
      await logout.mutateAsync();
      navigate("/signin");
    } catch {
      setError("We could not sign you out. Please try again.");
    }
  }
  return (
    <main className="page-shell product-shell">
      <div className="product-workspace">
        <header className="product-topbar">
          <a
            className="product-brand"
            href="/products"
            onClick={linkTo("/products")}
          >
            Launchpad <span>{workspaceLabel}</span>
          </a>
          <nav aria-label="Your account" className="product-account-nav">
            <a href="/profile" onClick={linkTo("/profile")}>
              Profile
            </a>
            <button
              disabled={logout.isPending}
              onClick={() => void signOut()}
              type="button"
            >
              {logout.isPending ? "Signing out…" : "Sign out"}
            </button>
          </nav>
        </header>
        {error ? (
          <p role="alert" className="product-alert">
            {error}
          </p>
        ) : null}
        {children}
      </div>
    </main>
  );
}

function ProductHome({
  client,
  session,
}: {
  client: ProductClient;
  session: Awaited<ReturnType<IdentityClient["currentSession"]>>;
}) {
  const products = useViewerProducts(client);
  const create = useCreateDraft(client);
  const [error, setError] = useState("");
  const drafts =
    products.data?.items.filter(
      (item) => item.status === "draft" || item.status === "changes_requested",
    ) ?? [];
  const pending =
    products.data?.items.filter((item) => item.status === "submitted") ?? [];
  async function createDraft() {
    setError("");
    try {
      const product = await create.mutateAsync();
      navigate(`/products/${product.id}`);
    } catch (caught) {
      setError(
        caught instanceof ProductRequestError &&
          caught.status === 409 &&
          drafts.length >= 10
          ? "You have reached the 10 private draft limit. Delete a draft before creating another."
          : "We could not create a draft. Please try again.",
      );
    }
  }
  return (
    <section aria-labelledby="products-title" className="product-panel">
      <p className="eyebrow">Founder workspace</p>
      <h1 id="products-title">Your products</h1>
      <p className="product-intro">
        Drafts stay private. Only complete, verified submissions enter staff
        review.
      </p>
      <div className="product-counts" aria-label="Product limits">
        <span>
          Private drafts <strong>{drafts.length}/10</strong>
        </span>
        <span>
          In review <strong>{pending.length}/3</strong>
        </span>
        {!session.verified ? (
          <span className="product-unverified">
            Email not verified — drafting is available; submission is not.
          </span>
        ) : null}
        {session.suspended ? (
          <span className="product-unverified">
            Your account is suspended. Existing submissions may be withdrawn,
            but drafts cannot be changed.
          </span>
        ) : null}
      </div>
      {canReviewQueue(session) ? (
        <p className="product-staff-link">
          <a href="/products/review" onClick={linkTo("/products/review")}>
            Open staff review queue
          </a>
        </p>
      ) : null}
      {products.isPending ? (
        <p role="status">Loading your private products…</p>
      ) : null}
      {products.isError ? (
        <p role="alert" className="product-alert">
          Your product list is unavailable. Try again.
        </p>
      ) : null}
      {products.data && products.data.items.length === 0 ? (
        <div className="product-empty">
          <h2>Start with a private draft</h2>
          <p>You can save an unfinished idea and return to it later.</p>
        </div>
      ) : null}
      {products.data && products.data.items.length > 0 ? (
        <ul className="product-list" aria-label="Your private products">
          {products.data.items.map((product) => (
            <li key={product.id}>
              <a
                href={`/products/${product.id}`}
                onClick={linkTo(`/products/${product.id}`)}
              >
                <span className="product-list-title">
                  {product.name?.trim() || "Untitled product"}
                </span>
                <span>
                  {product.pitch?.trim() || "No short description yet"}
                </span>
                <span
                  className={`product-status product-status-${product.status}`}
                >
                  {productStatusLabel(product.status)}
                </span>
              </a>
            </li>
          ))}
        </ul>
      ) : null}
      {error ? (
        <p role="alert" className="product-alert">
          {error}
        </p>
      ) : null}
      <button
        className="primary-button"
        disabled={create.isPending || session.suspended || drafts.length >= 10}
        onClick={() => void createDraft()}
        type="button"
      >
        {create.isPending ? "Creating draft…" : "Create a product draft"}
      </button>
    </section>
  );
}

function StaffReviewQueue({ client }: { client: ProductClient }) {
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

function StaffApprovedReviewList({ client }: { client: ProductClient }) {
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

function StaffReviewDetail({
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

function canReviewQueue(
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

function productStatusLabel(status: string): string {
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

function createReviewIdempotencyKey(): string {
  if (typeof globalThis.crypto?.randomUUID === "function")
    return globalThis.crypto.randomUUID();
  return `review-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function ProductEditor({
  client,
  identityClient,
  productId,
  session,
}: {
  client: ProductClient;
  identityClient: IdentityClient;
  productId: string;
  session: Awaited<ReturnType<IdentityClient["currentSession"]>>;
}) {
  const product = useViewerProduct(client, productId);
  if (product.isPending)
    return (
      <section className="product-panel">
        <p role="status">Loading your private draft…</p>
      </section>
    );
  if (product.isError)
    return (
      <section className="product-panel">
        <h1>Product unavailable</h1>
        <p role="alert" className="product-alert">
          This product is unavailable or you may not have access.
        </p>
        <button
          className="secondary-button"
          onClick={() => navigate("/products")}
          type="button"
        >
          Back to your products
        </button>
      </section>
    );
  if (!product.data)
    return (
      <section className="product-panel">
        <h1>Product unavailable</h1>
        <p>This private product could not be found.</p>
        <button
          className="secondary-button"
          onClick={() => navigate("/products")}
          type="button"
        >
          Back to your products
        </button>
      </section>
    );
  if (
    product.data.summary.status === "approved" ||
    product.data.summary.status === "rejected"
  )
    return <LockedFounderProduct product={product.data} />;
  return (
    <ProductEditorForm
      key={product.data.summary.id}
      client={client}
      identityClient={identityClient}
      product={product.data}
      reload={product.refetch}
      session={session}
    />
  );
}

function LockedFounderProduct({ product }: { product: ProductDetail }) {
  const approved = product.summary.status === "approved";
  return (
    <section aria-labelledby="locked-product-title" className="product-panel">
      <button
        className="back-link-button"
        onClick={() => navigate("/products")}
        type="button"
      >
        ← Your products
      </button>
      <p className="eyebrow">Founder workspace</p>
      <h1 id="locked-product-title">
        {product.summary.name?.trim() || "Your product"}
      </h1>
      <span className={`product-status product-status-${product.summary.status}`}>
        {productStatusLabel(product.summary.status)}
      </span>
      <section
        aria-labelledby="locked-outcome-title"
        className="review-outcome"
      >
        <h2 id="locked-outcome-title">Latest review outcome</h2>
        <p>
          {approved
            ? "This product is approved and locked while it waits for the launch workflow."
            : "This product was rejected. Rejected products cannot be edited or resubmitted in this workflow."}
        </p>
        {product.reviewOutcome?.feedback ? (
          <p className="review-feedback">{product.reviewOutcome.feedback}</p>
        ) : null}
      </section>
      <p>{product.summary.pitch}</p>
      <p>{product.description}</p>
    </section>
  );
}

function ProductEditorForm({
  client,
  identityClient,
  product,
  reload,
  session,
}: {
  client: ProductClient;
  identityClient: IdentityClient;
  product: ProductDetail;
  reload: () => Promise<unknown>;
  session: Awaited<ReturnType<IdentityClient["currentSession"]>>;
}) {
  const initial: ProductDraftValues & { version: number } = {
    version: product.summary.version,
    name: product.summary.name ?? "",
    pitch: product.summary.pitch ?? "",
    description: product.description ?? "",
    website_url: product.websiteUrl ?? "",
    topic_names: product.topics.map((topic) => topic.displayName),
  };
  const pendingRef = useRef(product.summary.status === "submitted");
  const autosave = useProductAutosave(
    client,
    product.summary.id,
    initial,
    500,
    (values) =>
      isValidDraftValues(values) &&
      (!pendingRef.current || isCompleteContent(values)),
  );
  const topicChoices = useTopicChoices(client);
  const submit = useSubmitProduct(client);
  const attach = useAttachProductAssets(client, product.summary.id);
  const remove = useDeleteProductDraft(client, product.summary.id);
  const withdraw = useWithdrawProduct(client, product.summary.id);
  const [selection, setSelection] = useState<Selection>(() => ({
    logo: product.assets.find((asset) => asset.kind === "logo")?.id ?? "",
    screenshots: product.assets
      .filter((asset) => asset.kind === "screenshot")
      .map((asset) => asset.id),
  }));
  const [persistedSelection, setPersistedSelection] = useState<Selection>(
    () => ({
      logo: product.assets.find((asset) => asset.kind === "logo")?.id ?? "",
      screenshots: product.assets
        .filter((asset) => asset.kind === "screenshot")
        .map((asset) => asset.id),
    }),
  );
  const [localAssets, setLocalAssets] = useState<LocalAsset[]>([]);
  const localAssetsRef = useRef(localAssets);
  localAssetsRef.current = localAssets;
  useEffect(
    () => () => {
      if (typeof URL.revokeObjectURL === "function")
        localAssetsRef.current.forEach((asset) =>
          URL.revokeObjectURL(asset.previewUrl),
        );
    },
    [],
  );
  const [uploading, setUploading] = useState(0);
  const uploadPromises = useRef(new Set<Promise<void>>());
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [pendingWithdrawn, setPendingWithdrawn] = useState(false);
  const [pendingSubmitted, setPendingSubmitted] = useState(false);
  const [isSavingMedia, setIsSavingMedia] = useState(false);
  const isPending =
    (product.summary.status === "submitted" || pendingSubmitted) &&
    !pendingWithdrawn;
  const readOnly = session.suspended;
  const canDeleteDraft =
    product.summary.status === "draft" && !product.reviewOutcome;
  const editorBusy = readOnly || isSavingMedia;
  const values = autosave.values;
  const topics = useMemo(
    () => splitTopics(values.topic_names ?? []),
    [values.topic_names],
  );
  const selectionChanged = !sameSelection(selection, persistedSelection);
  const allAssets: Array<AttachedAsset | LocalAsset> = [
    ...product.assets,
    ...localAssets,
  ];
  const logoChoices = allAssets.filter((asset) => asset.kind === "logo");
  const screenshotChoices = allAssets.filter(
    (asset) => asset.kind === "screenshot",
  );
  const pendingIncomplete = isPending && !isCompleteContent(values);
  const contentComplete = isCompleteContent(values);
  const fieldErrors = draftFieldErrors(values, submitAttempted);
  const mediaComplete =
    Boolean(selection.logo) &&
    selection.screenshots.length >= 1 &&
    selection.screenshots.length <= 10;
  const canSubmit =
    !isPending &&
    !readOnly &&
    !isSavingMedia &&
    session.verified &&
    contentComplete &&
    mediaComplete &&
    !selectionChanged &&
    uploading === 0;
  const blockers = submissionBlockers(
    values,
    selection,
    selectionChanged,
    uploading,
  );

  async function handleUpload(
    file: File | undefined,
    kind: "logo" | "screenshot",
  ) {
    if (!file) return;
    setError("");
    setNotice("");
    if (readOnly || isPending)
      return setError("Media cannot be changed in this account state.");
    if (
      !IMAGE_TYPES.has(file.type) ||
      file.size <= 0 ||
      file.size > MAX_IMAGE_BYTES
    )
      return setError(
        "Use a JPEG, PNG, or WebP image larger than 0 and up to 5 MB.",
      );
    if (kind === "screenshot" && selection.screenshots.length >= 10)
      return setError("A product can have at most 10 screenshots.");

    const operation = Promise.resolve().then(async () => {
      setUploading((count) => count + 1);
      try {
        const intent = await client.createAssetIntent(product.summary.id, {
          kind,
          content_type: file.type as "image/jpeg" | "image/png" | "image/webp",
          size: file.size,
        });
        await client.uploadAsset(intent.upload_url, intent.fields, file);
        const completed = await client.completeAsset(
          product.summary.id,
          intent.asset_id,
        );
        if (completed.state !== "clean")
          throw new Error("The image did not pass validation.");
        const candidate: LocalAsset = {
          id: completed.asset_id,
          kind: completed.kind,
          mediaType: completed.media_type,
          byteCount: completed.byte_count,
          previewUrl: URL.createObjectURL(file),
          fileName: file.name,
        };
        setLocalAssets((items) => [...items, candidate]);
        setNotice(
          "Image validated. Select it below and save the media selection to attach it.",
        );
      } catch {
        setError(
          "Photo upload could not be completed. Check the file and try again.",
        );
      } finally {
        uploadPromises.current.delete(operation);
        setUploading((count) => Math.max(0, count - 1));
      }
    });
    uploadPromises.current.add(operation);
    await operation;
  }

  async function saveMedia() {
    setError("");
    setNotice("");
    setIsSavingMedia(true);
    try {
      const saved = await autosave.saveLatest();
      const result = await attach.mutateAsync({
        version: saved.version,
        logo_asset_id: selection.logo || null,
        screenshot_asset_ids: selection.screenshots,
      });
      autosave.adoptVersion(result.version);
      setPersistedSelection({
        ...selection,
        screenshots: [...selection.screenshots],
      });
      const attachedIds = new Set([selection.logo, ...selection.screenshots]);
      localAssets
        .filter((asset) => attachedIds.has(asset.id))
        .forEach((asset) => {
          if (typeof URL.revokeObjectURL === "function")
            URL.revokeObjectURL(asset.previewUrl);
        });
      setLocalAssets((items) =>
        items.filter((asset) => !attachedIds.has(asset.id)),
      );
      setNotice("Selected media is attached to this private draft.");
      try {
        await reload();
      } catch {
        setNotice(
          "Media is attached. The latest product view could not be refreshed.",
        );
      }
    } catch (caught) {
      setError(
        caught instanceof ProductRequestError && caught.status === 409
          ? "The product changed elsewhere. Your selection is still here; reload the latest version before retrying."
          : "We could not save this media selection. Your choices are still here; try again.",
      );
    } finally {
      setIsSavingMedia(false);
    }
  }

  async function submitForReview(event: FormEvent) {
    event.preventDefault();
    setSubmitAttempted(true);
    setError("");
    setNotice("");
    if (!canSubmit) {
      setError(
        uploading > 0
          ? "Wait for every image upload and validation to finish before submitting."
          : !session.verified
            ? "Verify your email before submitting this product."
            : "Complete the highlighted fields and submission checklist before submitting.",
      );
      return;
    }
    try {
      await submit.mutateAsync({
        productId: product.summary.id,
        readiness: {
          waitForUploads: async () => {
            if (uploadPromises.current.size > 0)
              await Promise.all([...uploadPromises.current]);
          },
          saveLatest: async () => {
            const saved = await autosave.saveLatest();
            return { version: saved.version };
          },
        },
      });
      pendingRef.current = true;
      setPendingSubmitted(true);
      setNotice("Your product is now in the review queue.");
    } catch (caught) {
      setError(
        caught instanceof ProductRequestError && caught.status === 409
          ? "The product changed or your pending limit was reached. Refresh and review the latest state."
          : "We could not submit your product. Your private draft is still available.",
      );
      return;
    }
    try {
      await reload();
    } catch {
      setNotice(
        "Your product was submitted. The latest view could not be refreshed.",
      );
    }
  }

  async function retryConflict() {
    if (
      !window.confirm(
        "Save the edits currently shown here over the newer saved version? Your displayed values will replace that version.",
      )
    )
      return;
    setError("");
    try {
      const result = await reload();
      const refreshed = result as { data?: ProductDetail | null };
      if (!refreshed.data)
        throw new Error("Latest product version is unavailable.");
      await autosave.rebaseAndSave(refreshed.data.summary.version);
      setNotice("Your displayed edits were saved over the latest version.");
    } catch {
      setError(
        "We could not resolve the version conflict. Your displayed edits are still here.",
      );
    }
  }

  async function deleteDraft() {
    if (
      !window.confirm(
        "Permanently delete this private draft and its uploaded images? This cannot be undone.",
      )
    )
      return;
    setError("");
    try {
      await remove.mutateAsync(autosave.version);
      navigate("/products");
    } catch (caught) {
      setError(
        caught instanceof ProductRequestError && caught.status === 503
          ? "Deletion failed because storage is temporarily unavailable. Your draft is still here; retry when ready."
          : "We could not delete this draft. It is still available for retry.",
      );
    }
  }

  async function withdrawSubmission() {
    if (!product.submission) return;
    if (
      !window.confirm(
        "Withdraw this submission? It will leave the review queue; submitting again later starts at the back.",
      )
    )
      return;
    setError("");
    setNotice("");
    let result: Awaited<ReturnType<typeof withdraw.mutateAsync>>;
    try {
      result = await withdraw.mutateAsync({
        submissionId: product.submission.id,
        version: autosave.version,
      });
    } catch {
      setError("We could not withdraw this submission. Refresh and try again.");
      return;
    }
    pendingRef.current = false;
    setPendingWithdrawn(true);
    autosave.adoptVersion(result.version);
    try {
      await autosave.saveLatest();
      await reload();
      setNotice("Submission withdrawn. Your changes are now a private draft.");
    } catch {
      setNotice(
        "Submission withdrawn. Refresh the page to confirm your saved draft changes.",
      );
    }
  }

  function toggleScreenshot(assetId: string) {
    setError("");
    if (selection.screenshots.includes(assetId)) {
      setSelection({
        ...selection,
        screenshots: selection.screenshots.filter((id) => id !== assetId),
      });
      return;
    }
    if (selection.screenshots.length >= 10)
      return setError("A product can have at most 10 screenshots.");
    setSelection({
      ...selection,
      screenshots: [...selection.screenshots, assetId],
    });
  }

  function moveScreenshot(index: number, direction: -1 | 1) {
    setSelection((current) => {
      const next = [...current.screenshots];
      const target = index + direction;
      if (target < 0 || target >= next.length) return current;
      [next[index], next[target]] = [next[target], next[index]];
      return { ...current, screenshots: next };
    });
  }

  function editTopics(value: string) {
    autosave.edit({
      topic_names: value
        .split("\n")
        .map((topic) => topic.trim())
        .filter(Boolean),
    });
  }

  return (
    <section
      aria-labelledby="editor-title"
      className="product-panel product-editor"
    >
      <button
        className="back-link-button"
        onClick={() => navigate("/products")}
        type="button"
      >
        ← Your products
      </button>
      <div className="product-editor-heading">
        <div>
          <p className="eyebrow">
            {isPending
              ? "Submitted for review"
              : productStatusLabel(product.summary.status)}
          </p>
          <h1 id="editor-title">{values.name?.trim() || "Your product"}</h1>
        </div>
        <p
          className={`autosave-status autosave-${autosave.status}`}
          aria-live="polite"
          aria-atomic="true"
          role="status"
        >
          {autosaveCopy(autosave.status)}
        </p>
      </div>
      <p className="product-intro">
        {isPending
          ? "This complete version is waiting for staff review. Valid edits keep your place in the queue."
          : product.summary.status === "changes_requested"
            ? "Make private corrections below. Partial edits can be saved; complete the submission checklist before resubmitting."
            : "Your product stays private until a later launch workflow publishes it."}
      </p>
      {product.summary.status === "changes_requested" &&
      product.reviewOutcome?.feedback ? (
        <section
          aria-labelledby="correction-feedback-title"
          className="review-outcome"
        >
          <h2 id="correction-feedback-title">Changes requested</h2>
          <p className="review-feedback">{product.reviewOutcome.feedback}</p>
        </section>
      ) : null}
      {session.suspended ? (
        <p className="product-notice">
          Your account is suspended. You can withdraw an existing submission,
          but cannot edit, upload, submit, or delete.
        </p>
      ) : null}
      {!session.verified ? (
        <p className="product-notice">
          You can draft before email verification. Verify your email before
          submitting this product.
        </p>
      ) : null}
      {Object.values(fieldErrors).some(Boolean) ? (
        <div className="product-alert" role="alert">
          <p>Review these field errors before continuing:</p>
          <ul>
            {Object.entries(fieldErrors).map(([field, message]) =>
              message ? <li key={field}>{message}</li> : null,
            )}
          </ul>
        </div>
      ) : null}

      <form
        className="product-form"
        onSubmit={(event) => void submitForReview(event)}
      >
        <fieldset disabled={editorBusy} className="product-fields">
          <legend>Product details</legend>
          <label className="product-field" htmlFor="product-name">
            <span>
              Name <small>up to 80 characters</small>
            </span>
            <input
              aria-invalid={fieldErrors.name ? true : undefined}
              id="product-name"
              maxLength={80}
              value={values.name ?? ""}
              onChange={(event) => autosave.edit({ name: event.target.value })}
              aria-describedby={
                fieldErrors.name
                  ? "product-name-help product-name-error"
                  : "product-name-help"
              }
            />
            <small id="product-name-help">
              {(values.name ?? "").length}/80 characters
            </small>
            {fieldErrors.name ? (
              <small className="product-field-error" id="product-name-error">
                {fieldErrors.name}
              </small>
            ) : null}
          </label>
          <label className="product-field" htmlFor="product-pitch">
            <span>
              One-line pitch <small>up to 160 characters</small>
            </span>
            <input
              aria-invalid={fieldErrors.pitch ? true : undefined}
              id="product-pitch"
              maxLength={160}
              value={values.pitch ?? ""}
              onChange={(event) => autosave.edit({ pitch: event.target.value })}
              aria-describedby={
                fieldErrors.pitch
                  ? "product-pitch-help product-pitch-error"
                  : "product-pitch-help"
              }
            />
            <small id="product-pitch-help">
              {(values.pitch ?? "").length}/160 characters
            </small>
            {fieldErrors.pitch ? (
              <small className="product-field-error" id="product-pitch-error">
                {fieldErrors.pitch}
              </small>
            ) : null}
          </label>
          <label className="product-field" htmlFor="product-description">
            <span>
              Description <small>up to 5,000 characters</small>
            </span>
            <textarea
              aria-invalid={fieldErrors.description ? true : undefined}
              id="product-description"
              maxLength={5000}
              rows={7}
              value={values.description ?? ""}
              onChange={(event) =>
                autosave.edit({ description: event.target.value })
              }
              aria-describedby={
                fieldErrors.description
                  ? "product-description-help product-description-error"
                  : "product-description-help"
              }
            />
            <small id="product-description-help">
              {(values.description ?? "").length}/5,000 characters
            </small>
            {fieldErrors.description ? (
              <small
                className="product-field-error"
                id="product-description-error"
              >
                {fieldErrors.description}
              </small>
            ) : null}
          </label>
          <label className="product-field" htmlFor="product-website">
            <span>
              Product website <small>public HTTPS link</small>
            </span>
            <input
              aria-invalid={fieldErrors.website ? true : undefined}
              id="product-website"
              type="url"
              inputMode="url"
              placeholder="https://example.com"
              value={values.website_url ?? ""}
              onChange={(event) =>
                autosave.edit({ website_url: event.target.value })
              }
              aria-describedby={
                fieldErrors.website
                  ? "product-website-help product-website-error"
                  : "product-website-help"
              }
            />
            <small id="product-website-help">
              Use a complete https:// address.
            </small>
            {fieldErrors.website ? (
              <small className="product-field-error" id="product-website-error">
                {fieldErrors.website}
              </small>
            ) : null}
          </label>
          <div className="product-field">
            <label htmlFor="product-topics">
              <span>
                Topics{" "}
                <small>
                  one per line, 1–3 to submit; each up to 40 characters
                </small>
              </span>
            </label>
            <textarea
              aria-invalid={fieldErrors.topics ? true : undefined}
              id="product-topics"
              rows={3}
              value={topics.join("\n")}
              onChange={(event) => editTopics(event.target.value)}
              aria-describedby={
                fieldErrors.topics
                  ? "product-topics-help product-topics-error"
                  : "product-topics-help"
              }
            />
            <small id="product-topics-help">
              {topics.length}/3 topics. Launched topics and your own proposals
              appear as suggestions.
            </small>
            {fieldErrors.topics ? (
              <small className="product-field-error" id="product-topics-error">
                {fieldErrors.topics}
              </small>
            ) : null}
            {topicChoices.data && topicChoices.data.length > 0 ? (
              <div className="topic-suggestions">
                <label htmlFor="topic-suggestion">Suggestions</label>
                <select id="topic-suggestion" defaultValue="">
                  <option value="">Choose a topic to add</option>
                  {topicChoices.data.map((topic) => (
                    <option key={topic.id} value={topic.displayName}>
                      {topic.displayName}
                    </option>
                  ))}
                </select>
                <button
                  className="small-button"
                  onClick={(event) => {
                    const select = event.currentTarget
                      .previousElementSibling as HTMLSelectElement | null;
                    if (
                      select?.value &&
                      !topics.some(
                        (topic) =>
                          topic.toLocaleLowerCase() ===
                          select.value.toLocaleLowerCase(),
                      ) &&
                      topics.length < 3
                    )
                      editTopics([...topics, select.value].join("\n"));
                    if (select) select.value = "";
                  }}
                  type="button"
                >
                  Add topic
                </button>
              </div>
            ) : null}
          </div>
        </fieldset>

        <section aria-labelledby="media-title" className="product-media">
          <div>
            <h2 id="media-title">Product media</h2>
            <p>
              JPEG, PNG, or WebP up to 5 MB. Uploading validates privately;
              choose and save an image to attach it.
            </p>
          </div>
          <label className="file-picker">
            Upload logo
            <input
              accept="image/jpeg,image/png,image/webp"
              disabled={editorBusy || isPending || uploading > 0}
              onChange={(event) => {
                void handleUpload(event.target.files?.[0], "logo");
                event.currentTarget.value = "";
              }}
              type="file"
            />
          </label>
          <fieldset
            className="asset-picker"
            disabled={editorBusy || isPending || attach.isPending}
          >
            <legend>Choose one logo</legend>
            {logoChoices.length === 0 ? (
              <p>No validated logo uploaded yet.</p>
            ) : (
              logoChoices.map((asset) => (
                <label className="asset-choice" key={asset.id}>
                  <input
                    checked={selection.logo === asset.id}
                    name="product-logo"
                    onChange={() =>
                      setSelection((current) => ({
                        ...current,
                        logo: asset.id,
                      }))
                    }
                    type="radio"
                  />
                  <AssetPreview asset={asset} alt="Logo preview" />
                  <span>Logo · {formatBytes(asset.byteCount)}</span>
                </label>
              ))
            )}
            {selection.logo ? (
              <button
                className="small-button"
                onClick={() =>
                  setSelection((current) => ({ ...current, logo: "" }))
                }
                type="button"
              >
                Clear logo selection
              </button>
            ) : null}
          </fieldset>
          <label className="file-picker">
            Upload screenshot
            <input
              accept="image/jpeg,image/png,image/webp"
              disabled={
                editorBusy ||
                isPending ||
                uploading > 0 ||
                selection.screenshots.length >= 10
              }
              onChange={(event) => {
                void handleUpload(event.target.files?.[0], "screenshot");
                event.currentTarget.value = "";
              }}
              type="file"
            />
          </label>
          <fieldset
            className="asset-picker"
            disabled={editorBusy || isPending || attach.isPending}
          >
            <legend>
              Screenshots ({selection.screenshots.length}/10 selected)
            </legend>
            {screenshotChoices.length === 0 ? (
              <p>No validated screenshots uploaded yet.</p>
            ) : (
              screenshotChoices.map((asset) => (
                <label className="asset-choice" key={asset.id}>
                  <input
                    checked={selection.screenshots.includes(asset.id)}
                    onChange={() => toggleScreenshot(asset.id)}
                    type="checkbox"
                  />
                  <AssetPreview asset={asset} alt="Screenshot preview" />
                  <span>Screenshot · {formatBytes(asset.byteCount)}</span>
                </label>
              ))
            )}
            {selection.screenshots.map((assetId, index) => (
              <div className="asset-order" key={assetId}>
                <span>Screenshot {index + 1}</span>
                <button
                  aria-label={`Move screenshot ${index + 1} earlier`}
                  className="small-button"
                  disabled={index === 0}
                  onClick={() => moveScreenshot(index, -1)}
                  type="button"
                >
                  Move up
                </button>
                <button
                  aria-label={`Move screenshot ${index + 1} later`}
                  className="small-button"
                  disabled={index === selection.screenshots.length - 1}
                  onClick={() => moveScreenshot(index, 1)}
                  type="button"
                >
                  Move down
                </button>
              </div>
            ))}
          </fieldset>
          {uploading > 0 ? (
            <p role="alert" className="product-alert">
              An image is still being uploaded and validated. Submission will
              wait until it finishes.
            </p>
          ) : null}
          {localAssets.length > 0 ? (
            <p className="product-muted">
              Validated but unattached:{" "}
              {localAssets.map((asset) => asset.fileName).join(", ")}
            </p>
          ) : null}
          <button
            className="secondary-button"
            disabled={
              readOnly ||
              isPending ||
              attach.isPending ||
              uploading > 0 ||
              !selectionChanged
            }
            onClick={() => void saveMedia()}
            type="button"
          >
            {attach.isPending ? "Saving media…" : "Save media selection"}
          </button>
          {selectionChanged ? (
            <p className="product-muted">
              Your selected media is not attached yet. Save the selection before
              submitting.
            </p>
          ) : null}
        </section>

        <section
          aria-labelledby="submission-title"
          className="submission-section"
        >
          <h2 id="submission-title">Ready for staff review?</h2>
          <ul
            aria-label="Submission checklist"
            className="submission-checklist"
          >
            {blockers.map((item) => (
              <li
                className={item.complete ? "complete" : "incomplete"}
                key={item.label}
              >
                {item.label}
              </li>
            ))}
          </ul>
          {pendingIncomplete ? (
            <p className="product-notice" role="status">
              A pending submission must remain complete. Your incomplete edits
              are kept here but not saved; withdraw to continue this work as a
              private draft.
            </p>
          ) : null}
          {isPending ? (
            <button
              className="secondary-button"
              disabled={withdraw.isPending}
              onClick={() => void withdrawSubmission()}
              type="button"
            >
              {withdraw.isPending
                ? "Withdrawing…"
                : "Withdraw to private draft"}
            </button>
          ) : null}
          {!isPending ? (
            <button
              className="primary-button"
              disabled={readOnly || submit.isPending}
              type="submit"
            >
              {submit.isPending
                ? "Saving and submitting…"
                : "Submit for staff review"}
            </button>
          ) : null}
          {!session.verified && !isPending ? (
            <button
              className="text-button"
              disabled={readOnly}
              onClick={async () => {
                try {
                  await identityClient.requestVerification();
                  setNotice(
                    "If your account can receive verification email, a fresh link is on its way.",
                  );
                } catch {
                  setError(
                    "We could not request a verification email. Try again later.",
                  );
                }
              }}
              type="button"
            >
              Request verification email
            </button>
          ) : null}
        </section>
      </form>

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
      {autosave.status === "not-saved" && !pendingIncomplete && !readOnly ? (
        <button
          className="small-button"
          onClick={() => void autosave.retry().catch(() => undefined)}
          type="button"
        >
          Retry saving your edits
        </button>
      ) : null}
      {autosave.status === "conflict" ? (
        <div className="product-conflict" role="alert">
          <p>
            Your edits are still here, but a newer version was saved elsewhere.
          </p>
          <button
            className="secondary-button"
            onClick={() => void retryConflict()}
            type="button"
          >
            Review latest and save my displayed edits
          </button>
        </div>
      ) : null}
      {isPending ? (
        <p className="product-muted">
          Attachments are read-only while this submission is in review. Withdraw
          first to change media.
        </p>
      ) : null}
      {canDeleteDraft ? (
        <button
          className="danger-button"
          disabled={readOnly || remove.isPending}
          onClick={() => void deleteDraft()}
          type="button"
        >
          {remove.isPending ? "Deleting draft…" : "Delete private draft"}
        </button>
      ) : null}
      <button
        className="back-link-button"
        onClick={() => navigate("/products")}
        type="button"
      >
        Back to your products
      </button>
    </section>
  );
}

function AssetPreview({
  asset,
  alt,
}: {
  asset: AttachedAsset | LocalAsset;
  alt: string;
}) {
  const src = "url" in asset ? asset.url : asset.previewUrl;
  return <img alt={alt} className="asset-preview" src={src} />;
}

function submissionBlockers(
  values: ProductDraftValues,
  selection: Selection,
  selectionChanged: boolean,
  uploading: number,
) {
  const topics = splitTopics(values.topic_names ?? []);
  return [
    {
      label: "Product name (1–80 characters)",
      complete:
        Boolean(values.name?.trim()) && (values.name?.trim().length ?? 0) <= 80,
    },
    {
      label: "One-line pitch (1–160 characters)",
      complete:
        Boolean(values.pitch?.trim()) &&
        (values.pitch?.trim().length ?? 0) <= 160,
    },
    {
      label: "Description (1–5,000 characters)",
      complete:
        Boolean(values.description?.trim()) &&
        (values.description?.trim().length ?? 0) <= 5000,
    },
    {
      label: "Public HTTPS product website",
      complete: isHttpsUrl(values.website_url ?? ""),
    },
    { label: "One validated logo", complete: Boolean(selection.logo) },
    {
      label: "1–10 validated screenshots",
      complete:
        selection.screenshots.length >= 1 && selection.screenshots.length <= 10,
    },
    {
      label: "1–3 distinct topics (up to 40 characters each)",
      complete:
        topics.length >= 1 &&
        topics.length <= 3 &&
        topics.every((topic) => topic.length <= 40) &&
        new Set(topics.map((topic) => topic.toLocaleLowerCase())).size ===
          topics.length,
    },
    {
      label: "Media selection attached; no upload in progress",
      complete: !selectionChanged && uploading === 0,
    },
  ];
}

function isCompleteContent(values: ProductDraftValues): boolean {
  const topics = splitTopics(values.topic_names ?? []);
  return (
    Boolean(values.name?.trim()) &&
    (values.name?.trim().length ?? 0) <= 80 &&
    Boolean(values.pitch?.trim()) &&
    (values.pitch?.trim().length ?? 0) <= 160 &&
    Boolean(values.description?.trim()) &&
    (values.description?.trim().length ?? 0) <= 5000 &&
    isHttpsUrl(values.website_url ?? "") &&
    topics.length >= 1 &&
    topics.length <= 3 &&
    topics.every((topic) => topic.length <= 40) &&
    new Set(topics.map((topic) => topic.toLocaleLowerCase())).size ===
      topics.length
  );
}

function isValidDraftValues(values: ProductDraftValues): boolean {
  return (
    (values.name?.length ?? 0) <= 80 &&
    (values.pitch?.length ?? 0) <= 160 &&
    (values.description?.length ?? 0) <= 5000 &&
    (!(values.website_url ?? "").trim() ||
      isHttpsUrl(values.website_url ?? "")) &&
    splitTopics(values.topic_names ?? []).length <= 3 &&
    splitTopics(values.topic_names ?? []).every(
      (topic) => topic.length <= 40,
    ) &&
    new Set(
      splitTopics(values.topic_names ?? []).map((topic) =>
        topic.toLocaleLowerCase(),
      ),
    ).size === splitTopics(values.topic_names ?? []).length
  );
}

type ProductFieldErrorKey =
  | "name"
  | "pitch"
  | "description"
  | "website"
  | "topics";

function draftFieldErrors(
  values: ProductDraftValues,
  submitAttempted: boolean,
): Partial<Record<ProductFieldErrorKey, string>> {
  const errors: Partial<Record<ProductFieldErrorKey, string>> = {};
  if ((values.name?.length ?? 0) > 80)
    errors.name = "Name must be 80 characters or fewer.";
  else if (submitAttempted && !values.name?.trim())
    errors.name = "Enter a product name.";
  if ((values.pitch?.length ?? 0) > 160)
    errors.pitch = "Pitch must be 160 characters or fewer.";
  else if (submitAttempted && !values.pitch?.trim())
    errors.pitch = "Enter a one-line pitch.";
  if ((values.description?.length ?? 0) > 5000)
    errors.description = "Description must be 5,000 characters or fewer.";
  else if (submitAttempted && !values.description?.trim())
    errors.description = "Enter a product description.";
  if (
    (values.website_url ?? "").trim() &&
    !isHttpsUrl(values.website_url ?? "")
  )
    errors.website = "Website must be a valid HTTPS URL.";
  else if (submitAttempted && !isHttpsUrl(values.website_url ?? ""))
    errors.website = "Enter a public HTTPS product website.";
  const topics = splitTopics(values.topic_names ?? []);
  if (
    topics.length > 3 ||
    topics.some((topic) => topic.length > 40) ||
    new Set(topics.map((topic) => topic.toLocaleLowerCase())).size !==
      topics.length
  )
    errors.topics =
      "Topics must be 1–3 distinct names, each 40 characters or fewer.";
  else if (submitAttempted && topics.length < 1)
    errors.topics = "Choose or create at least one topic.";
  return errors;
}

function splitTopics(topics: string[] | null): string[] {
  return (topics ?? []).map((topic) => topic.trim()).filter(Boolean);
}

function isHttpsUrl(value: string): boolean {
  try {
    return (
      new URL(value).protocol === "https:" && Boolean(new URL(value).hostname)
    );
  } catch {
    return false;
  }
}

function sameSelection(left: Selection, right: Selection): boolean {
  return (
    left.logo === right.logo &&
    left.screenshots.join("\u0000") === right.screenshots.join("\u0000")
  );
}

function formatBytes(value: number): string {
  return value >= 1024 * 1024
    ? `${(value / (1024 * 1024)).toFixed(1)} MB`
    : `${Math.max(1, Math.round(value / 1024))} KB`;
}

function autosaveCopy(
  status: ReturnType<typeof useProductAutosave>["status"],
): string {
  switch (status) {
    case "saved":
      return "Saved";
    case "saving":
      return "Saving…";
    case "dirty":
      return "Unsaved changes";
    case "not-saved":
      return "Not saved";
    case "conflict":
      return "Needs conflict resolution";
  }
}

function linkTo(path: string) {
  return (event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    navigate(path);
  };
}
