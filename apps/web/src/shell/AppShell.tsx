import {
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";
import { useCurrentSession, useLogout } from "../identity/useIdentity";
import type { IdentityClient } from "../identity/client";
import { navigate } from "../routing";
import { NotificationBell } from "../notifications/NotificationBell";
import { LoadingState, StatusBanner, UnavailableState } from "../ui/Primitives";
import "./shell.css";

type ShellProps = { children: ReactNode };

export function PublicShell({
  children,
  identityClient,
}: ShellProps & { identityClient: IdentityClient }) {
  const session = useCurrentSession(identityClient);
  const logout = useLogout(identityClient);
  const [signOutError, setSignOutError] = useState("");

  async function signOut() {
    setSignOutError("");
    try {
      await logout.mutateAsync();
      navigate("/signin");
    } catch {
      setSignOutError("We could not sign you out. Please try again.");
    }
  }

  const account = session.isError ? undefined : session.data;

  return (
    <div className="app-shell app-shell--public">
      <a className="app-skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="app-header app-header--public">
        <a className="app-brand" href="/" onClick={handleNavigation("/")}>
          LAUNCHPAD
          <span>PRODUCT LAUNCH WORKSPACE</span>
        </a>
        <nav aria-label="Public navigation" className="app-public-nav">
          <a href="/" onClick={handleNavigation("/")}>
            Home
          </a>
          <a href="/discover" onClick={handleNavigation("/discover")}>
            Discover
          </a>
          {!session.isPending && !session.isError && !account ? (
            <>
              <a href="/signin" onClick={handleNavigation("/signin")}>
                Sign in
              </a>
              <a
                className="ui-action ui-action--primary"
                href="/register"
                onClick={handleNavigation("/register")}
              >
                Create account
              </a>
            </>
          ) : null}
          {account ? (
            <>
              {account.suspended ? (
                <span className="app-public-nav-label">Access paused</span>
              ) : !account.verified ? (
                <a href="/verify" onClick={handleNavigation("/verify")}>
                  Verify email
                </a>
              ) : account.role === "member" ? (
                <a href="/products" onClick={handleNavigation("/products")}>
                  Your workspace
                </a>
              ) : (
                <a
                  href="/products/review"
                  onClick={handleNavigation("/products/review")}
                >
                  Review queue
                </a>
              )}
              <button
                className="ui-action ui-action--secondary"
                disabled={logout.isPending}
                onClick={() => void signOut()}
                type="button"
              >
                {logout.isPending ? "Signing out…" : "Sign out"}
              </button>
            </>
          ) : null}
        </nav>
      </header>
      <main className="app-main" id="main-content" tabIndex={-1}>
        {signOutError ? (
          <StatusBanner variant="danger">{signOutError}</StatusBanner>
        ) : null}
        {children}
      </main>
      <footer className="app-footer">
        <span>LAUNCHPAD</span>
        <span>Prepare. Review. Schedule. Publish.</span>
      </footer>
    </div>
  );
}

export function WorkspaceShell({
  children,
  identityClient,
}: ShellProps & { identityClient: IdentityClient }) {
  const session = useCurrentSession(identityClient);
  const logout = useLogout(identityClient);
  const [menuOpen, setMenuOpen] = useState(false);
  const [signOutError, setSignOutError] = useState("");
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const navigationRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    navigationRef.current?.querySelector<HTMLElement>("a, button")?.focus();
  }, [menuOpen]);

  useEffect(() => {
    if (!menuOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      menuButtonRef.current?.focus();
    };
    const closeOnRouteChange = () => setMenuOpen(false);
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("popstate", closeOnRouteChange);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("popstate", closeOnRouteChange);
    };
  }, [menuOpen]);

  async function signOut() {
    setSignOutError("");
    setMenuOpen(false);
    try {
      await logout.mutateAsync();
      navigate("/signin");
    } catch {
      setSignOutError("We could not sign you out. Please try again.");
    }
  }

  const account = session.isError ? null : session.data;
  const eligible = Boolean(account?.verified && !account.suspended);
  const reviewer = Boolean(
    eligible && (account?.role === "reviewer" || account?.role === "admin"),
  );
  const member = Boolean(eligible && account?.role === "member");

  let content: ReactNode;
  if (session.isPending) {
    content = (
      <LoadingState
        title="Checking your workspace"
        description="We’re confirming your account access."
      />
    );
  } else if (session.isError) {
    content = (
      <UnavailableState
        title="Workspace unavailable"
        description="We couldn’t confirm access. Try again or sign in again."
        action={
          <a className="ui-action ui-action--secondary" href="/signin">
            Sign in
          </a>
        }
      />
    );
  } else if (!account) {
    content = (
      <UnavailableState
        title="Sign in to continue"
        description="Your workspace is private. Sign in to continue to your Launchpad work."
        action={
          <a className="ui-action ui-action--primary" href="/signin">
            Sign in
          </a>
        }
      />
    );
  } else if (!member && !reviewer) {
    content = (
      <UnavailableState
        title={
          account.suspended ? "Workspace access paused" : "Verify your email"
        }
        description={
          account.suspended
            ? "This account cannot access the workspace right now."
            : "Confirm your email address to access your workspace."
        }
        action={
          account.suspended ? undefined : (
            <a className="ui-action ui-action--secondary" href="/verify">
              Verify email
            </a>
          )
        }
      />
    );
  } else {
    content = children;
  }

  const roleLabel = reviewer ? "REVIEWER WORKSPACE" : "FOUNDER WORKSPACE";
  const navigation = reviewer
    ? [
        { href: "/products/review", label: "Review queue" },
        { href: "/votes/reviews", label: "Vote flags" },
        {
          href: "/products/review#approved-reviews-title",
          label: "Decision history",
        },
      ]
    : [
        { href: "/products", label: "Your products" },
        { href: "/launches", label: "Launch calendar" },
        { href: "/profile", label: "Profile" },
      ];

  return (
    <div className="app-shell app-shell--workspace">
      <a className="app-skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="app-header app-header--workspace">
        <a
          className="app-brand"
          href={reviewer ? "/products/review" : "/products"}
          onClick={handleNavigation(
            reviewer ? "/products/review" : "/products",
          )}
        >
          LAUNCHPAD
          <span>{eligible ? roleLabel : "PRIVATE WORKSPACE"}</span>
        </a>
        {member ? (
          <div className="app-notification-slot">
            <NotificationBell identityClient={identityClient} />
          </div>
        ) : null}
        <button
          aria-controls="workspace-navigation"
          aria-expanded={menuOpen}
          aria-label={menuOpen ? "Close workspace menu" : "Open workspace menu"}
          className="app-menu-toggle"
          onClick={() => setMenuOpen((open) => !open)}
          ref={menuButtonRef}
          type="button"
        >
          <span aria-hidden="true">{menuOpen ? "×" : "☰"}</span>
        </button>
        <nav
          aria-label={reviewer ? "Reviewer workspace" : "Founder workspace"}
          className={`app-workspace-nav${menuOpen ? " is-open" : ""}`}
          id="workspace-navigation"
          ref={navigationRef}
        >
          {eligible
            ? navigation.map((item) => (
                <a
                  href={item.href}
                  key={item.href}
                  onClick={handleNavigation(item.href, () =>
                    setMenuOpen(false),
                  )}
                >
                  {item.label}
                </a>
              ))
            : null}
          {account ? (
            <button
              disabled={logout.isPending}
              onClick={() => void signOut()}
              type="button"
            >
              {logout.isPending ? "Signing out…" : "Sign out"}
            </button>
          ) : (
            <a href="/signin" onClick={handleNavigation("/signin")}>
              Sign in
            </a>
          )}
        </nav>
      </header>
      <main className="app-main" id="main-content" tabIndex={-1}>
        {signOutError ? (
          <StatusBanner variant="danger">{signOutError}</StatusBanner>
        ) : null}
        {content}
      </main>
      <footer className="app-footer">
        <span>LAUNCHPAD</span>
        <span>{eligible ? roleLabel : "PRIVATE WORKSPACE"}</span>
      </footer>
    </div>
  );
}

function handleNavigation(path: string, afterNavigate?: () => void) {
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
    afterNavigate?.();
    navigate(path);
  };
}
