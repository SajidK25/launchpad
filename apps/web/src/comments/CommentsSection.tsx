import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import type { IdentityClient } from "../identity/client";
import { useCurrentSession } from "../identity/useIdentity";
import { createProfileClient } from "../profiles/client";
import { profileKeys } from "../profiles/useProfile";
import {
  CommentRequestError,
  createCommentsClient,
  type CommentCommandResult,
  type DiscussionEntry,
  type DiscussionThread,
} from "./client";
import {
  flattenDiscussionPages,
  flattenReplyPages,
  useCommentReplies,
  useCreateComment,
  useCreateReply,
  useDiscussion,
} from "./useComments";
import { useCommentsLive } from "./useCommentsLive";

type Session = Awaited<ReturnType<IdentityClient["currentSession"]>>;
type ViewerProfile = Awaited<
  ReturnType<ReturnType<typeof createProfileClient>["fetchViewerProfile"]>
>;

export function CommentsSection({
  identityClient,
  productId,
}: {
  identityClient: IdentityClient;
  productId: string;
}) {
  const client = useMemo(
    () => createCommentsClient(undefined, identityClient),
    [identityClient],
  );
  const profileClient = useMemo(
    () =>
      createProfileClient(
        undefined,
        () => identityClient.getCsrfToken(),
        () => identityClient.ensureSession(),
      ),
    [identityClient],
  );
  const session = useCurrentSession(identityClient);
  const member = session.data?.role === "member" ? session.data : null;
  const profile = useQuery({
    queryKey: profileKeys.viewer,
    queryFn: profileClient.fetchViewerProfile,
    enabled: member !== null,
  });
  const discussion = useDiscussion(client, productId);
  const [loadedParents, setLoadedParents] = useState<Set<string>>(new Set());
  const live = useCommentsLive({
    client,
    productId,
    enabled: !discussion.isError,
    loadedParentIds: loadedParents,
  });
  const [confirmedRoots, setConfirmedRoots] = useState<CommentCommandResult[]>(
    [],
  );
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (live.closed) setConfirmedRoots([]);
  }, [live.closed]);

  if (discussion.isPending) {
    return (
      <section
        aria-labelledby="discussion-heading"
        className="comments-section"
      >
        <h2 id="discussion-heading">Discussion</h2>
        <p role="status">Loading discussion…</p>
      </section>
    );
  }
  if (discussion.isError || live.closed) return null;

  const viewerProfile = profile.data ?? null;
  const eligibility = postingEligibility(session.data ?? null, viewerProfile);
  const serverThreads = flattenDiscussionPages(discussion.data?.pages ?? []);
  const confirmedThreads = confirmedRoots.map((entry) =>
    confirmedRoot(entry, session.data ?? null, viewerProfile),
  );
  const threads = uniqueEntries([...confirmedThreads, ...serverThreads]);

  async function revealNewActivity() {
    await live.showNewActivity();
    headingRef.current?.focus();
  }

  return (
    <section aria-labelledby="discussion-heading" className="comments-section">
      <header className="comments-heading">
        <div>
          <p className="launch-kicker">COMMUNITY NOTES</p>
          <h2 id="discussion-heading" ref={headingRef} tabIndex={-1}>
            Discussion
          </h2>
        </div>
        <span aria-live="polite" className="comments-live-state">
          {live.connected ? "Live" : "Reconnecting…"}
        </span>
      </header>

      {live.newActivityCount > 0 ? (
        <button
          className="comments-new-activity"
          onClick={() => void revealNewActivity()}
          type="button"
        >
          {live.newActivityCount === 1
            ? "1 new comment"
            : `${live.newActivityCount} new comments`}
        </button>
      ) : null}

      <ParticipationState eligibility={eligibility} />
      {eligibility === "eligible" ? (
        <CommentComposer
          label="Add to the discussion"
          onConfirmed={(entry) =>
            setConfirmedRoots((current) =>
              uniqueCommandEntries([entry, ...current]),
            )
          }
          productId={productId}
          client={client}
        />
      ) : null}

      {threads.length === 0 ? (
        <p className="comments-empty">
          No comments yet. Start the conversation.
        </p>
      ) : (
        <ol aria-label="Product discussion" className="comments-thread-list">
          {threads.map((thread) => (
            <CommentThread
              client={client}
              eligibility={eligibility}
              key={thread.id}
              onLoaded={(parentId) =>
                setLoadedParents((current) => new Set(current).add(parentId))
              }
              productId={productId}
              thread={thread}
              viewerProfile={viewerProfile}
              viewerSession={session.data ?? null}
            />
          ))}
        </ol>
      )}

      {discussion.hasNextPage ? (
        <button
          className="launch-button comments-page-button"
          disabled={discussion.isFetchingNextPage}
          onClick={() => void discussion.fetchNextPage()}
          type="button"
        >
          {discussion.isFetchingNextPage ? "Loading…" : "Load older comments"}
        </button>
      ) : null}
    </section>
  );
}

type Eligibility =
  | "eligible"
  | "signed-out"
  | "unverified"
  | "suspended"
  | "staff"
  | "incomplete";

function postingEligibility(
  session: Session | null,
  profile: ViewerProfile | null,
): Eligibility {
  if (session === null) return "signed-out";
  if (session.suspended) return "suspended";
  if (!session.verified) return "unverified";
  if (session.role !== "member") return "staff";
  if (!profile?.displayName.trim() || !profile.photoUrl) return "incomplete";
  return "eligible";
}

function ParticipationState({ eligibility }: { eligibility: Eligibility }) {
  if (eligibility === "eligible") return null;
  const copy = {
    "signed-out": "Sign in to join the discussion.",
    unverified: "Verify your email to join the discussion.",
    suspended: "Your access is paused. You can still read the discussion.",
    staff: "Staff accounts can read this discussion but cannot post.",
    incomplete: "Complete your name and profile photo before posting.",
  }[eligibility];
  return (
    <p className="comments-participation">
      {copy}{" "}
      {eligibility === "signed-out" ? <a href="/signin">Sign in</a> : null}
      {eligibility === "unverified" ? <a href="/verify">Verify email</a> : null}
      {eligibility === "incomplete" ? (
        <a href="/profile">Complete profile</a>
      ) : null}
    </p>
  );
}

function CommentComposer({
  client,
  label,
  onConfirmed,
  productId,
}: {
  client: ReturnType<typeof createCommentsClient>;
  label: string;
  onConfirmed: (entry: CommentCommandResult) => void;
  productId: string;
}) {
  const mutation = useCreateComment(client, productId);
  return (
    <Composer
      label={label}
      onConfirmed={onConfirmed}
      submit={(body, idempotencyKey) =>
        mutation.mutateAsync({ body, idempotencyKey })
      }
      submitting={mutation.isPending}
    />
  );
}

function ReplyComposer({
  client,
  onConfirmed,
  parentId,
  productId,
}: {
  client: ReturnType<typeof createCommentsClient>;
  onConfirmed: (entry: CommentCommandResult) => void;
  parentId: string;
  productId: string;
}) {
  const mutation = useCreateReply(client, productId, parentId);
  return (
    <Composer
      label="Write a reply"
      onConfirmed={onConfirmed}
      submit={(body, idempotencyKey) =>
        mutation.mutateAsync({ body, idempotencyKey })
      }
      submitting={mutation.isPending}
    />
  );
}

function Composer({
  label,
  onConfirmed,
  submit,
  submitting,
}: {
  label: string;
  onConfirmed: (entry: CommentCommandResult) => void;
  submit: (
    body: string,
    idempotencyKey: string,
  ) => Promise<CommentCommandResult>;
  submitting: boolean;
}) {
  const [draft, setDraft] = useState("");
  const [attemptKey, setAttemptKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const errorRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    const key = attemptKey ?? crypto.randomUUID();
    setAttemptKey(key);
    try {
      const entry = await submit(draft, key);
      onConfirmed(entry);
      setDraft("");
      setAttemptKey(null);
      setNotice(
        entry.replayed ? "Your comment is published." : "Comment published.",
      );
    } catch (caught) {
      setError(commentErrorMessage(caught));
    }
  }

  return (
    <form
      className="comments-composer"
      onSubmit={(event) => void handleSubmit(event)}
    >
      <label>
        <span>{label}</span>
        <textarea
          maxLength={2000}
          onChange={(event) => {
            setDraft(event.target.value);
            setAttemptKey(null);
          }}
          required
          rows={4}
          value={draft}
        />
      </label>
      <div className="comments-composer-footer">
        <span>{draft.length}/2000</span>
        <button
          className="launch-button launch-button-yellow"
          disabled={submitting}
          type="submit"
        >
          {submitting ? "Publishing…" : "Publish"}
        </button>
      </div>
      {error ? (
        <p className="launch-error" ref={errorRef} role="alert" tabIndex={-1}>
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="launch-success" role="status">
          {notice}
        </p>
      ) : null}
    </form>
  );
}

function CommentThread({
  client,
  eligibility,
  onLoaded,
  productId,
  thread,
  viewerProfile,
  viewerSession,
}: {
  client: ReturnType<typeof createCommentsClient>;
  eligibility: Eligibility;
  onLoaded: (parentId: string) => void;
  productId: string;
  thread: DiscussionThread;
  viewerProfile: ViewerProfile | null;
  viewerSession: Session | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const [replying, setReplying] = useState(false);
  const [confirmedReplies, setConfirmedReplies] = useState<
    CommentCommandResult[]
  >([]);
  const earlier = useCommentReplies(client, productId, thread.id, 20, expanded);
  const loaded = expanded ? flattenReplyPages(earlier.data?.pages ?? []) : [];
  const confirmed = confirmedReplies.map((entry) =>
    confirmedReply(entry, viewerSession, viewerProfile),
  );
  const replies = uniqueEntries([
    ...loaded,
    ...thread.replies,
    ...confirmed,
  ]).sort((left, right) => left.createdAt.localeCompare(right.createdAt));

  return (
    <li className="comments-thread">
      <Entry entry={thread} />
      {replies.length > 0 ? (
        <ol
          aria-label={`Replies to ${thread.author.displayName}`}
          className="comments-replies"
        >
          {replies.map((reply) => (
            <li key={reply.id}>
              <Entry entry={reply} />
            </li>
          ))}
        </ol>
      ) : null}
      <div className="comments-thread-actions">
        {thread.replyCount > thread.replies.length ? (
          <button
            className="launch-text-link"
            disabled={earlier.isFetchingNextPage}
            onClick={() => {
              if (!expanded) {
                setExpanded(true);
                onLoaded(thread.id);
              } else if (earlier.hasNextPage) void earlier.fetchNextPage();
            }}
            type="button"
          >
            {earlier.isFetchingNextPage ? "Loading…" : "View earlier replies"}
          </button>
        ) : null}
        {eligibility === "eligible" ? (
          <button
            className="launch-text-link"
            onClick={() => setReplying((value) => !value)}
            type="button"
          >
            {replying ? "Cancel reply" : "Reply"}
          </button>
        ) : null}
      </div>
      {replying ? (
        <ReplyComposer
          client={client}
          onConfirmed={(entry) => {
            setConfirmedReplies((current) =>
              uniqueCommandEntries([...current, entry]),
            );
            setReplying(false);
          }}
          parentId={thread.id}
          productId={productId}
        />
      ) : null}
    </li>
  );
}

function Entry({ entry }: { entry: DiscussionEntry | DiscussionThread }) {
  const name = entry.author.displayName;
  return (
    <article className="comments-entry">
      <img
        alt=""
        className="comments-avatar"
        height="44"
        src={entry.author.avatarUrl}
        width="44"
      />
      <div>
        <header>
          {entry.author.publicProfileUrl ? (
            <a href={entry.author.publicProfileUrl}>{name}</a>
          ) : (
            <strong>{name}</strong>
          )}
          <time dateTime={entry.createdAt}>
            {formatCommentDate(entry.createdAt)}
          </time>
        </header>
        <p>{entry.body}</p>
      </div>
    </article>
  );
}

function confirmedRoot(
  entry: CommentCommandResult,
  session: Session | null,
  profile: ViewerProfile | null,
): DiscussionThread {
  return {
    ...confirmedReply(entry, session, profile),
    replyCount: 0,
    replies: [],
  };
}

function confirmedReply(
  entry: CommentCommandResult,
  session: Session | null,
  profile: ViewerProfile | null,
): DiscussionEntry {
  return {
    id: entry.id,
    productId: entry.product_id,
    parentId: entry.parent_id,
    body: entry.body,
    createdAt: entry.created_at,
    author: {
      accountId: session?.account_id ?? "viewer",
      displayName: profile?.displayName ?? "You",
      avatarUrl: profile?.photoUrl ?? "",
      publicProfileUrl: null,
    },
  };
}

function uniqueEntries<T extends { id: string }>(entries: readonly T[]): T[] {
  return [...new Map(entries.map((entry) => [entry.id, entry])).values()];
}

function uniqueCommandEntries(entries: readonly CommentCommandResult[]) {
  return uniqueEntries(entries);
}

function commentErrorMessage(error: unknown): string {
  if (error instanceof CommentRequestError) {
    if (error.kind === "limited")
      return "You’re posting too quickly. Your draft is saved; try again later.";
    if (error.kind === "conflict")
      return "That comment could not be published. Your draft is saved; review it and retry.";
    if (error.kind === "invalid") return error.detail;
  }
  return "We could not confirm publication. Your draft is saved; retry with the same text.";
}

function formatCommentDate(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
