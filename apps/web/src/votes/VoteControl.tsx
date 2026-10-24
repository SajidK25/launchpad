import { useCallback, useEffect, useRef, useState } from "react";
import { useCurrentSession } from "../identity/useIdentity";
import type { IdentityClient } from "../identity/client";
import { navigate } from "../routing";
import { VoteRequestError } from "./client";
import { useVoteCommand } from "./useVotes";
import "./votes.css";

type TurnstileWidget = {
  render: (
    container: HTMLElement,
    options: {
      sitekey: string;
      callback: (token: string) => void;
      "expired-callback": () => void;
      "error-callback": () => void;
      theme: "light";
    },
  ) => string;
  remove: (widgetId: string) => void;
};

declare global {
  interface Window {
    turnstile?: TurnstileWidget;
  }
}

const configuredSiteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY?.trim() ?? "";

export function VoteControl({
  identityClient,
  productId,
  launchDate,
  activeVoteCount,
  viewerVoted,
  votingOpen,
  siteKey = configuredSiteKey,
}: {
  identityClient: IdentityClient;
  productId: string;
  launchDate: string;
  activeVoteCount: number | null;
  viewerVoted: boolean | null;
  votingOpen: boolean;
  siteKey?: string;
}) {
  const session = useCurrentSession(identityClient);
  const mutation = useVoteCommand(identityClient, productId, launchDate);
  const [confirmedVote, setConfirmedVote] = useState(viewerVoted);
  const [challengeToken, setChallengeToken] = useState<string | null>(null);
  const attempt = useRef<{ active: boolean; key: string } | null>(null);
  const clearChallengeToken = useCallback(() => setChallengeToken(null), []);
  const productPath = `/launches/${encodeURIComponent(productId)}`;

  useEffect(() => setConfirmedVote(viewerVoted), [viewerVoted]);

  if (session.isPending)
    return (
      <p className="vote-control-state" role="status">
        Checking voting access…
      </p>
    );
  if (session.isError)
    return (
      <p className="vote-control-state" role="alert">
        Voting access could not be checked. Refresh and try again.
      </p>
    );
  if (!votingOpen)
    return (
      <p className="vote-control-state">Voting is closed for this launch.</p>
    );
  if (!session.data)
    return (
      <a
        className="vote-control-signin"
        href={`/signin?returnTo=${encodeURIComponent(productPath)}`}
        onClick={(event) => {
          event.preventDefault();
          navigate(`/signin?returnTo=${encodeURIComponent(productPath)}`);
        }}
      >
        Sign in to vote
      </a>
    );
  if (session.data.role !== "member")
    return <p className="vote-control-state">Voting is for members.</p>;
  if (session.data.suspended)
    return (
      <p className="vote-control-state">
        Voting is unavailable while your account is suspended.
      </p>
    );
  if (!session.data.verified)
    return (
      <p className="vote-control-state">
        Verify your email in <a href="/profile">your profile</a> to vote.
      </p>
    );
  if (viewerVoted === null && confirmedVote === null)
    return (
      <p className="vote-control-state" role="status">
        Vote status is not available for this account.
      </p>
    );

  const hasVoted = confirmedVote ?? viewerVoted ?? false;
  const challengeRequested =
    mutation.error instanceof VoteRequestError && mutation.error.status === 422;
  const challengeFailed =
    challengeRequested && Boolean(mutation.variables?.turnstileToken);
  const active = !hasVoted;

  async function submit(activeVote: boolean, token?: string) {
    if (attempt.current?.active !== activeVote) {
      attempt.current = { active: activeVote, key: crypto.randomUUID() };
    }
    const idempotencyKey = attempt.current.key;
    try {
      const result = await mutation.mutateAsync({
        active: activeVote,
        idempotencyKey,
        ...(token ? { turnstileToken: token } : {}),
      });
      setConfirmedVote(result.active);
      setChallengeToken(null);
      attempt.current = null;
    } catch (error) {
      if (error instanceof VoteRequestError && error.status === 422)
        setChallengeToken(null);
    }
  }

  const errorMessage = mutation.error ? voteErrorMessage(mutation.error) : "";

  return (
    <div className="vote-control">
      <button
        aria-pressed={hasVoted}
        className="vote-control-button"
        disabled={mutation.isPending || challengeRequested}
        onClick={() => void submit(active)}
        type="button"
      >
        {mutation.isPending
          ? hasVoted
            ? "Removing vote…"
            : "Recording vote…"
          : mutation.isError && !challengeRequested
            ? hasVoted
              ? "Retry remove vote"
              : "Retry vote"
            : hasVoted
              ? "Remove vote"
              : "Vote for this launch"}
      </button>
      {activeVoteCount === null ? null : (
        <span className="vote-control-count" aria-live="polite">
          {activeVoteCount} {activeVoteCount === 1 ? "vote" : "votes"}
        </span>
      )}
      {mutation.isSuccess && !mutation.isPending ? (
        <p className="vote-control-feedback" role="status">
          {mutation.data.active
            ? "Your vote is recorded. The ranking is refreshing."
            : "Your vote was removed. The ranking is refreshing."}
        </p>
      ) : null}
      {mutation.isError ? (
        <p className="vote-control-feedback vote-control-error" role="alert">
          {errorMessage}
        </p>
      ) : null}
      {challengeRequested ? (
        <div className="vote-control-challenge">
          <p role="status">
            {challengeFailed
              ? "The security check did not pass. Complete it again to continue."
              : "Complete the security check to continue voting."}
          </p>
          {siteKey ? (
            <TurnstileChallenge
              siteKey={siteKey}
              onError={clearChallengeToken}
              onToken={setChallengeToken}
            />
          ) : (
            <p className="vote-control-error" role="alert">
              Security verification is not configured in this deployment.
            </p>
          )}
          <button
            className="vote-control-button"
            disabled={!challengeToken || mutation.isPending || !siteKey}
            onClick={() => void submit(active, challengeToken ?? undefined)}
            type="button"
          >
            Verify and {active ? "vote" : "remove vote"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function TurnstileChallenge({
  siteKey,
  onToken,
  onError,
}: {
  siteKey: string;
  onToken: (token: string) => void;
  onError: () => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    const target = container.current;
    if (!target) return;
    let widgetId: string | null = null;
    const renderWidget = () => {
      if (!window.turnstile || widgetId !== null) return;
      widgetId = window.turnstile.render(target, {
        sitekey: siteKey,
        theme: "light",
        callback: onToken,
        "expired-callback": onError,
        "error-callback": () => {
          onError();
          setLoadError(true);
        },
      });
    };
    const script =
      document.querySelector<HTMLScriptElement>(
        'script[data-launchpad-turnstile="true"]',
      ) ?? document.createElement("script");
    const ownsScript = !script.isConnected;
    const onScriptError = () => setLoadError(true);
    if (ownsScript) {
      script.async = true;
      script.defer = true;
      script.dataset.launchpadTurnstile = "true";
      script.src =
        "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    }
    script.addEventListener("load", renderWidget);
    script.addEventListener("error", onScriptError, { once: true });
    if (window.turnstile) renderWidget();
    if (ownsScript) document.head.append(script);

    return () => {
      script.removeEventListener("load", renderWidget);
      script.removeEventListener("error", onScriptError);
      if (widgetId !== null) window.turnstile?.remove(widgetId);
    };
  }, [onError, onToken, siteKey]);

  return (
    <div>
      <div
        aria-label="Cloudflare security check"
        ref={container}
        role="group"
      />
      {loadError ? (
        <p className="vote-control-error" role="alert">
          The security check could not load. Refresh and try again.
        </p>
      ) : null}
    </div>
  );
}

function voteErrorMessage(error: unknown): string {
  if (!(error instanceof VoteRequestError))
    return "Your previous vote is unchanged. Please try again.";
  if (error.status === 401)
    return "Your session expired. Sign in again to vote.";
  if (error.status === 403)
    return "Voting is unavailable for this account or product. Check verification, suspension, and ownership requirements.";
  if (error.status === 404)
    return "This launch is no longer available for voting.";
  if (error.status === 409)
    return "Your vote changed in another tab. Refresh the page and try again.";
  if (error.status === 422)
    return "A security check is required before this vote can be accepted.";
  if (error.status === 429)
    return "Too many vote requests. Wait a moment, then retry.";
  if (error.status === 503)
    return "Voting is temporarily unavailable. Your previous vote is unchanged; retry shortly.";
  return "Your previous vote is unchanged. Please try again.";
}
