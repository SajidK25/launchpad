/** @vitest-environment jsdom */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IdentityClient } from "../identity/client";
import { HomePage } from "./HomePage";

const mocks = vi.hoisted(() => ({
  session: null as unknown,
  connectivity: null as unknown,
  navigate: vi.fn(),
  discoveryProps: null as unknown,
  discoveryState: "loaded" as "loaded" | "loading" | "empty" | "error",
}));

vi.mock("../identity/useIdentity", () => ({
  useCurrentSession: () => mocks.session,
}));
vi.mock("../connectivity/useConnectivity", () => ({
  useConnectivity: () => mocks.connectivity,
}));
vi.mock("../routing", () => ({ navigate: mocks.navigate }));
vi.mock("../launches/LaunchDiscovery", () => ({
  LaunchDiscovery: (props: {
    onDateChange: (date: string) => void;
    headingLevel?: "h1" | "h2";
  }) => {
    mocks.discoveryProps = props;
    const Heading = props.headingLevel ?? "h2";
    return (
      <section
        aria-labelledby="mock-launch-discovery-title"
        className="launch-panel"
        data-testid="launch-discovery"
      >
        <p>PUBLIC RELEASES</p>
        <Heading id="mock-launch-discovery-title">Today’s launches</Heading>
        {mocks.discoveryState === "loading" ? (
          <p role="status">Loading launches…</p>
        ) : mocks.discoveryState === "empty" ? (
          <p role="status">No launches on this day.</p>
        ) : mocks.discoveryState === "error" ? (
          <p role="alert">Launches could not be loaded. Try again.</p>
        ) : (
          <p>Today’s launch feed</p>
        )}
      </section>
    );
  },
}));

const identityClient = {} as IdentityClient;

function memberSession(role: "member" | "reviewer" | "admin" = "member") {
  return {
    data: {
      account_id: "private-account-id",
      csrf_token: "private-csrf-token",
      role,
      suspended: false,
      verified: true,
    },
    isPending: false,
    isError: false,
  };
}

function renderHome() {
  return render(<HomePage identityClient={identityClient} />);
}

function expectHomeDiscoveryVisible() {
  expect(
    screen.getByRole("heading", {
      level: 1,
      name: "Today’s launches",
    }),
  ).toBeTruthy();
  expect(screen.getByTestId("launch-discovery")).toBeTruthy();
}

function expectRetainedSectionsVisible() {
  expect(
    screen.getByRole("heading", {
      level: 2,
      name: "Take your product from ready to released.",
    }),
  ).toBeTruthy();
  expect(
    screen.getByRole("heading", { name: "A launch process you can follow" }),
  ).toBeTruthy();
  for (const step of ["Prepare", "Get reviewed", "Choose a date", "Publish"])
    expect(screen.getByRole("heading", { name: step })).toBeTruthy();
  expect(
    screen.getByRole("heading", {
      name: "Know where your launch stands.",
    }),
  ).toBeTruthy();
}

beforeEach(() => {
  mocks.session = { data: null, isPending: false, isError: false };
  mocks.connectivity = { state: "connected", refresh: vi.fn() };
  mocks.navigate.mockReset();
  mocks.discoveryProps = null;
  mocks.discoveryState = "loaded";
});

afterEach(() => cleanup());

describe("HomePage", () => {
  it("renders the launches first and restores all previous homepage sections", () => {
    const { container } = renderHome();

    expectHomeDiscoveryVisible();
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "Take your product from ready to released.",
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Create your account" }),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeTruthy();
    expect(
      screen.getByText(
        "Prepare your product, get a staff review, reserve a launch date, and share its public release page—all in one clear workflow.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Approved products can book one of the available UTC launch dates.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "A launch process you can follow" }),
    ).toBeTruthy();
    for (const step of ["Prepare", "Get reviewed", "Choose a date", "Publish"])
      expect(screen.getByRole("heading", { name: step })).toBeTruthy();
    expect(
      screen.getByRole("heading", {
        name: "Know where your launch stands.",
      }),
    ).toBeTruthy();

    const sections = Array.from(
      container.querySelectorAll(
        ".launch-panel, .home-hero, .home-journey, .home-principles",
      ),
      (element) => element.className,
    );
    expect(sections).toEqual([
      "launch-panel",
      "home-hero",
      "home-journey",
      "home-principles",
    ]);
    expect(
      (mocks.discoveryProps as { headingLevel?: string }).headingLevel,
    ).toBe("h1");
  });

  it.each(["loading", "empty", "error"] as const)(
    "keeps all supporting homepage sections visible when the feed is %s",
    (state) => {
      mocks.discoveryState = state;
      const { container } = renderHome();

      expectHomeDiscoveryVisible();
      if (state === "loading" || state === "empty")
        expect(screen.getByRole("status")).toBeTruthy();
      else
        expect(screen.getByRole("alert").textContent).toContain(
          "could not be loaded",
        );
      expect(
        screen.getByRole("heading", {
          name: "Take your product from ready to released.",
        }),
      ).toBeTruthy();
      expect(
        screen.getByRole("heading", {
          name: "A launch process you can follow",
        }),
      ).toBeTruthy();
      expect(
        screen.getByRole("heading", {
          name: "Know where your launch stands.",
        }),
      ).toBeTruthy();
      const sectionOrder = Array.from(
        container.querySelectorAll(
          ".launch-panel, .home-hero, .home-journey, .home-principles",
        ),
        (element) => element.className,
      );
      expect(sectionOrder).toEqual([
        "launch-panel",
        "home-hero",
        "home-journey",
        "home-principles",
      ]);
    },
  );

  it("keeps the homepage action destinations intact", () => {
    renderHome();

    expect(
      screen
        .getByRole("link", { name: "Create your account" })
        .getAttribute("href"),
    ).toBe("/register");
    expect(
      screen.getByRole("link", { name: "Sign in" }).getAttribute("href"),
    ).toBe("/signin");
  });

  it("routes a selected past date to its public archive", () => {
    renderHome();
    const discovery = mocks.discoveryProps as {
      onDateChange: (date: string) => void;
    };

    discovery.onDateChange("2026-10-21");

    expect(mocks.navigate).toHaveBeenCalledWith(
      "/launches/archive/2026-10-21",
      { focusMainContent: true },
    );
  });

  it("routes an eligible member to the founder workspace", () => {
    mocks.session = memberSession();
    renderHome();

    expect(
      screen
        .getByRole("link", { name: "Go to your workspace" })
        .getAttribute("href"),
    ).toBe("/products");
    expect(
      screen.queryByRole("link", { name: "Create your account" }),
    ).toBeNull();
    expectRetainedSectionsVisible();
    fireEvent.click(screen.getByRole("link", { name: "Go to your workspace" }));
    expect(mocks.navigate).toHaveBeenCalledWith("/products");
  });

  it("routes an eligible reviewer to the review workspace", () => {
    mocks.session = memberSession("reviewer");
    renderHome();

    expect(
      screen
        .getByRole("link", { name: "Open review workspace" })
        .getAttribute("href"),
    ).toBe("/products/review");
    expect(
      screen.queryByRole("link", { name: "Create your account" }),
    ).toBeNull();
  });

  it("keeps unresolved or failed sessions on public actions without exposing account data", () => {
    mocks.session = {
      ...memberSession(),
      isPending: true,
      isError: true,
      error: new Error("private session response"),
    };
    renderHome();

    expectHomeDiscoveryVisible();
    expect(
      screen.getByRole("link", { name: "Create your account" }),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /workspace/i })).toBeNull();
    expect(document.body.textContent).not.toContain("private-account-id");
    expect(document.body.textContent).not.toContain("private session response");
  });

  it.each(["loading", "connected"] as const)(
    "keeps the landing content in place while connectivity is %s",
    (state) => {
      mocks.connectivity = { state, refresh: vi.fn() };
      renderHome();

      expectHomeDiscoveryVisible();
      expect(screen.queryByRole("alert")).toBeNull();
    },
  );

  it("shows a recovery action during an outage and clears it after recovery", () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    mocks.connectivity = { state: "unavailable", refresh };
    const view = renderHome();

    expectHomeDiscoveryVisible();
    expect(screen.getByRole("alert").textContent).toContain(
      "temporarily unavailable",
    );
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(refresh).toHaveBeenCalledOnce();

    mocks.connectivity = { state: "connected", refresh };
    view.rerender(<HomePage identityClient={identityClient} />);
    expectHomeDiscoveryVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
