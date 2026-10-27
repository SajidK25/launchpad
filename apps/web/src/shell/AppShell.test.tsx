/** @vitest-environment jsdom */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IdentityClient } from "../identity/client";
import { PublicShell, WorkspaceShell } from "./AppShell";

const mocks = vi.hoisted(() => ({
  session: null as unknown,
  logout: { isPending: false, mutateAsync: vi.fn() },
  navigate: vi.fn(),
}));

vi.mock("../identity/useIdentity", () => ({
  useCurrentSession: () => mocks.session,
  useLogout: () => mocks.logout,
}));
vi.mock("../notifications/NotificationBell", () => ({
  NotificationBell: () => <button type="button">Mock notifications</button>,
}));
vi.mock("../routing", () => ({ navigate: mocks.navigate }));

const identityClient = {} as IdentityClient;

function session(role: "member" | "reviewer" | "admin" = "member") {
  return {
    data: {
      account_id: "account-private-id",
      csrf_token: "csrf-private-token",
      role,
      suspended: false,
      verified: true,
    },
    isPending: false,
    isError: false,
  };
}

function renderPublic(children = <p>Public content</p>) {
  return render(
    <PublicShell identityClient={identityClient}>{children}</PublicShell>,
  );
}

function renderWorkspace(children = <p>Private workspace content</p>) {
  return render(
    <WorkspaceShell identityClient={identityClient}>{children}</WorkspaceShell>,
  );
}

beforeEach(() => {
  mocks.session = session();
  mocks.logout = {
    isPending: false,
    mutateAsync: vi.fn().mockResolvedValue(undefined),
  };
  mocks.navigate.mockReset();
});

afterEach(() => cleanup());

describe("PublicShell", () => {
  it("frames signed-out content with guest actions and no private links", () => {
    mocks.session = { data: null, isPending: false, isError: false };
    renderPublic(<h1>Welcome to Launchpad</h1>);

    expect(
      screen
        .getByRole("link", { name: "Skip to content" })
        .getAttribute("href"),
    ).toBe("#main-content");
    expect(
      screen.getByRole("navigation", { name: "Public navigation" }),
    ).toBeTruthy();
    expect(screen.getByRole("main")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Create account" })).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Discover" }).getAttribute("href"),
    ).toBe("/discover");
    expect(
      screen.getByRole("link", { name: "Discover" }).getAttribute("href"),
    ).toBe("/discover");
    expect(screen.queryByRole("link", { name: "Your products" })).toBeNull();
  });

  it("uses lightweight navigation for Discover", () => {
    renderPublic(<h1>Discover</h1>);
    fireEvent.click(screen.getByRole("link", { name: "Discover" }));
    expect(mocks.navigate).toHaveBeenCalledWith("/discover");
  });

  it.each([
    ["member", "Your workspace", "/products"],
    ["reviewer", "Review queue", "/products/review"],
    ["admin", "Review queue", "/products/review"],
  ] as const)(
    "shows the appropriate workspace link for a verified %s",
    (role, label, href) => {
      mocks.session = session(role);
      renderPublic();

      expect(
        screen.getByRole("link", { name: label }).getAttribute("href"),
      ).toBe(href);
      expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
      expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
      expect(screen.queryByRole("link", { name: "Create account" })).toBeNull();
    },
  );

  it("shows verification navigation for an unverified account", () => {
    mocks.session = {
      ...session(),
      data: { ...session().data, verified: false },
    };
    renderPublic();

    expect(screen.getByRole("link", { name: "Verify email" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Create account" })).toBeNull();
  });

  it("shows a paused label for a suspended account", () => {
    mocks.session = {
      ...session(),
      data: { ...session().data, suspended: true },
    };
    renderPublic();

    expect(screen.getByText("Access paused")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Your workspace" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Create account" })).toBeNull();
  });

  it("hides account actions while the shared session is loading or unavailable", () => {
    mocks.session = { data: undefined, isPending: true, isError: false };
    const view = renderPublic();

    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Create account" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();

    mocks.session = { data: undefined, isPending: false, isError: true };
    view.rerender(
      <PublicShell identityClient={identityClient}>
        <p>Public content</p>
      </PublicShell>,
    );
    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Create account" })).toBeNull();
  });

  it("updates account actions after login and logout without a page reload", () => {
    mocks.session = { data: null, isPending: false, isError: false };
    const view = renderPublic();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeTruthy();

    mocks.session = session();
    view.rerender(
      <PublicShell identityClient={identityClient}>
        <p>Public content</p>
      </PublicShell>,
    );
    expect(screen.getByRole("link", { name: "Your workspace" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();

    mocks.session = { data: null, isPending: false, isError: false };
    view.rerender(
      <PublicShell identityClient={identityClient}>
        <p>Public content</p>
      </PublicShell>,
    );
    expect(screen.getByRole("link", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Your workspace" })).toBeNull();
  });

  it("signs out through the shared mutation and navigates after success", async () => {
    renderPublic();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() =>
      expect(mocks.logout.mutateAsync).toHaveBeenCalledOnce(),
    );
    expect(mocks.navigate).toHaveBeenCalledWith("/signin");
  });
});

describe("WorkspaceShell", () => {
  it("withholds children, reviewer details, private navigation, and notifications while session is pending", () => {
    mocks.session = { data: undefined, isPending: true, isError: false };

    renderWorkspace(<p>PRIVATE FOUNDER DETAILS</p>);

    expect(screen.getByRole("status").textContent).toContain(
      "confirming your account",
    );
    expect(screen.queryByText("PRIVATE FOUNDER DETAILS")).toBeNull();
    expect(screen.queryByRole("link", { name: "Review queue" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Mock notifications" }),
    ).toBeNull();
    expect(document.body.textContent).not.toContain("account-private-id");
  });

  it("shows only a safe recovery state when the shared session query fails", () => {
    mocks.session = {
      ...session("reviewer"),
      isError: true,
      error: new Error("private session response"),
    };

    renderWorkspace(<p>PRIVATE FOUNDER DETAILS</p>);

    expect(
      screen.getByRole("heading", { name: "Workspace unavailable" }),
    ).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "Sign in" })).toHaveLength(2);
    expect(screen.queryByText("PRIVATE FOUNDER DETAILS")).toBeNull();
    expect(screen.queryByRole("link", { name: "Review queue" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Mock notifications" }),
    ).toBeNull();
    expect(document.body.textContent).not.toContain("private session response");
    expect(document.body.textContent).not.toContain("REVIEWER WORKSPACE");
  });

  it("shows founder destinations and one notification entry for an eligible member", () => {
    renderWorkspace();

    expect(screen.getByRole("link", { name: "Your products" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Launch calendar" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Profile" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Vote flags" })).toBeNull();
    const notifications = screen.getAllByRole("button", {
      name: "Mock notifications",
    });
    expect(notifications).toHaveLength(1);
    expect(notifications[0].closest(".app-notification-slot")).toBeTruthy();
    expect(screen.getByText("Private workspace content")).toBeTruthy();
  });

  it("emphasizes queue and decision history for reviewers without founder destinations", () => {
    mocks.session = session("reviewer");
    renderWorkspace();

    expect(
      screen.getByRole("link", { name: "Review queue" }).getAttribute("href"),
    ).toBe("/products/review");
    expect(
      screen.getByRole("link", { name: "Vote flags" }).getAttribute("href"),
    ).toBe("/votes/reviews");
    expect(
      screen
        .getByRole("link", { name: "Decision history" })
        .getAttribute("href"),
    ).toContain("approved-reviews-title");
    expect(screen.queryByRole("link", { name: "Your products" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Mock notifications" }),
    ).toBeNull();
  });

  it("updates destinations when the shared session role changes", () => {
    const view = renderWorkspace();
    expect(screen.getByRole("link", { name: "Your products" })).toBeTruthy();

    mocks.session = session("reviewer");
    view.rerender(
      <WorkspaceShell identityClient={identityClient}>
        <p>Private workspace content</p>
      </WorkspaceShell>,
    );

    expect(screen.getByRole("link", { name: "Review queue" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Vote flags" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Your products" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Mock notifications" }),
    ).toBeNull();
  });

  it("opens the disclosure into focus, restores focus on Escape, and closes after navigation", async () => {
    mocks.session = session("reviewer");
    renderWorkspace();

    const trigger = screen.getByRole("button", { name: "Open workspace menu" });
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("link", { name: "Review queue" }),
      ),
    );

    fireEvent.keyDown(document, { key: "Escape" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(trigger);

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("link", { name: "Review queue" }));
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(mocks.navigate).toHaveBeenCalledWith("/products/review");

    fireEvent.click(trigger);
    fireEvent(window, new PopStateEvent("popstate"));
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("keeps logout failure safe and lets the user retry", async () => {
    mocks.logout.mutateAsync.mockRejectedValueOnce(
      new Error("private server detail"),
    );
    renderWorkspace();

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("try again");
    expect(document.body.textContent).not.toContain("private server detail");
    expect(mocks.navigate).not.toHaveBeenCalled();
  });

  it("runs the existing logout mutation and navigates after success", async () => {
    renderWorkspace();

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() =>
      expect(mocks.logout.mutateAsync).toHaveBeenCalledOnce(),
    );
    expect(mocks.navigate).toHaveBeenCalledWith("/signin");
  });
});
