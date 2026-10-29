import { useMemo, type MouseEvent } from "react";
import type { IdentityClient } from "../identity/client";
import { useCurrentSession } from "../identity/useIdentity";
import { navigate } from "../routing";
import { useConnectivity } from "../connectivity/useConnectivity";
import { LaunchDiscovery } from "../launches/LaunchDiscovery";
import { createLaunchClient } from "../launches/client";
import { Action, StatusBanner } from "../ui/Primitives";
import "./home.css";

export function HomePage({
  identityClient,
}: {
  identityClient: IdentityClient;
}) {
  const session = useCurrentSession(identityClient);
  const connectivity = useConnectivity();
  const launchClient = useMemo(
    () => createLaunchClient(undefined, identityClient),
    [identityClient],
  );
  const account = session.isError ? null : session.data;
  const canEnterWorkspace = Boolean(account?.verified && !account.suspended);
  const reviewer = Boolean(
    canEnterWorkspace &&
      (account?.role === "reviewer" || account?.role === "admin"),
  );
  const workspacePath = reviewer ? "/products/review" : "/products";

  return (
    <div className="home-page">
      {connectivity.state === "unavailable" ? (
        <StatusBanner variant="danger">
          <div className="home-outage">
            <div>
              <strong>Launchpad is temporarily unavailable.</strong>
              <span>
                The launch process stays here. Check the connection and try
                again.
              </span>
            </div>
            <Action
              onClick={() => void connectivity.refresh()}
              variant="secondary"
            >
              Check again
            </Action>
          </div>
        </StatusBanner>
      ) : null}

      <section aria-labelledby="home-title" className="home-hero">
        <div className="home-hero-copy">
          <p className="ui-eyebrow">A more deliberate product launch</p>
          <h1 id="home-title">Take your product from ready to released.</h1>
          <p className="home-hero-description">
            Prepare your product, get a staff review, reserve a launch date, and
            share its public release page—all in one clear workflow.
          </p>
          <div className="home-actions">
            {canEnterWorkspace ? (
              <a
                className="ui-action ui-action--primary"
                href={workspacePath}
                onClick={internalLink(workspacePath)}
              >
                {reviewer ? "Open review workspace" : "Go to your workspace"}
              </a>
            ) : (
              <>
                <a
                  className="ui-action ui-action--primary"
                  href="/register"
                  onClick={internalLink("/register")}
                >
                  Create your account
                </a>
                <a
                  className="ui-action ui-action--secondary"
                  href="/signin"
                  onClick={internalLink("/signin")}
                >
                  Sign in
                </a>
              </>
            )}
          </div>
          <p className="home-hero-note">
            Approved products can book one of the available UTC launch dates.
          </p>
        </div>
        <div aria-hidden="true" className="home-hero-mark">
          <span>LP</span>
          <i />
          <i />
          <i />
        </div>
      </section>

      <LaunchDiscovery
        client={launchClient}
        headingLevel="h2"
        identityClient={identityClient}
        onDateChange={(date) =>
          navigate(`/launches/archive/${date}`, { focusMainContent: true })
        }
      />

      <section
        aria-labelledby="home-journey-title"
        className="home-journey"
        id="how-it-works"
      >
        <header className="home-section-heading">
          <p className="ui-eyebrow">One step at a time</p>
          <h2 id="home-journey-title">A launch process you can follow</h2>
          <p>
            Your work moves forward with clear decisions, dates, and next steps.
          </p>
        </header>
        <ol className="home-steps">
          <li className="home-step home-step--prepare">
            <span className="home-step-number">01</span>
            <h3>Prepare</h3>
            <p>
              Add your product details and media to a private draft. Submit it
              when it is ready for review.
            </p>
          </li>
          <li className="home-step home-step--review">
            <span className="home-step-number">02</span>
            <h3>Get reviewed</h3>
            <p>
              Launchpad staff review the submission and send a decision with any
              changes you need to make.
            </p>
          </li>
          <li className="home-step home-step--schedule">
            <span className="home-step-number">03</span>
            <h3>Choose a date</h3>
            <p>
              Once approved, reserve an available UTC launch date and keep track
              of reminders and updates.
            </p>
          </li>
          <li className="home-step home-step--publish">
            <span className="home-step-number">04</span>
            <h3>Publish</h3>
            <p>
              At 00:00 UTC on launch day, the eligible product page becomes
              public for people to visit.
            </p>
          </li>
        </ol>
      </section>

      <section
        aria-labelledby="home-principles-title"
        className="home-principles"
      >
        <div>
          <p className="ui-eyebrow">Clear status. Clear next step.</p>
          <h2 id="home-principles-title">Know where your launch stands.</h2>
        </div>
        <p>
          Drafts remain private. Review decisions include useful next steps.
          Approved products get a launch calendar, and publication happens on
          the date you booked.
        </p>
      </section>
    </div>
  );
}

function internalLink(path: string) {
  return (event: MouseEvent<HTMLAnchorElement>) => {
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    event.preventDefault();
    navigate(path);
  };
}
