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

      <section
        aria-labelledby="home-title"
        className="home-hero home-hero-compact"
      >
        <div className="home-hero-copy">
          <p className="ui-eyebrow">DISCOVER WHAT’S LAUNCHING</p>
          <h1 id="home-title">Fresh products. Every day.</h1>
          <p className="home-hero-description">
            Explore today’s releases from founders who prepared, reviewed, and
            scheduled their products on Launchpad.
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
        </div>
      </section>

      <LaunchDiscovery
        client={launchClient}
        onDateChange={(date) =>
          navigate(`/launches/archive/${date}`, { focusMainContent: true })
        }
      />
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
