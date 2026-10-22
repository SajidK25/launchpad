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
}));

vi.mock("../identity/useIdentity", () => ({
  useCurrentSession: () => mocks.session,
}));
vi.mock("../connectivity/useConnectivity", () => ({
  useConnectivity: () => mocks.connectivity,
}));
vi.mock("../routing", () => ({ navigate: mocks.navigate }));
vi.mock("../launches/LaunchDiscovery", () => ({
  LaunchDiscovery: (props: { onDateChange: (date: string) => void }) => {
    mocks.discoveryProps = props;
    return (
      <section aria-label="Today’s launches" data-testid="launch-discovery">
        Today’s launch feed
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
      name: "Fresh products. Every day.",
    }),
  ).toBeTruthy();
  expect(screen.getByTestId("launch-discovery")).toBeTruthy();
}

beforeEach(() => {
  mocks.session = { data: null, isPending: false, isError: false };
  mocks.connectivity = { state: "connected", refresh: vi.fn() };
  mocks.navigate.mockReset();
  mocks.discoveryProps = null;
});

afterEach(() => cleanup());

describe("HomePage", () => {
  it("makes today’s launches primary with a compact introduction", () => {
    renderHome();

    expectHomeDiscoveryVisible();
    expect(
      screen.getByRole("link", { name: "Create your account" }),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeTruthy();
    expect(screen.getByText(/Explore today’s releases/)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Prepare" })).toBeNull();
    expect(
      screen.queryByRole("heading", { name: /launch process/i }),
    ).toBeNull();
    expect(
      screen
        .getByRole("heading", { level: 1, name: "Fresh products. Every day." })
        .compareDocumentPosition(screen.getByTestId("launch-discovery")) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("routes a selected past date to its public archive", () => {
    renderHome();
    const discovery = mocks.discoveryProps as {
      onDateChange: (date: string) => void;
    };

    discovery.onDateChange("2026-10-21");

    expect(mocks.navigate).toHaveBeenCalledWith("/launches/archive/2026-10-21");
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
