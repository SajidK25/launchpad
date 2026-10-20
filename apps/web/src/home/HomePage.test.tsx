/** @vitest-environment jsdom */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IdentityClient } from "../identity/client";
import { HomePage } from "./HomePage";

const mocks = vi.hoisted(() => ({
  session: null as unknown,
  connectivity: null as unknown,
  navigate: vi.fn(),
}));

vi.mock("../identity/useIdentity", () => ({
  useCurrentSession: () => mocks.session,
}));
vi.mock("../connectivity/useConnectivity", () => ({
  useConnectivity: () => mocks.connectivity,
}));
vi.mock("../routing", () => ({ navigate: mocks.navigate }));

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

function expectJourneyVisible() {
  expect(
    screen.getByRole("heading", { level: 1, name: /ready to released/i }),
  ).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Prepare" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Get reviewed" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Choose a date" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Publish" })).toBeTruthy();
}

beforeEach(() => {
  mocks.session = { data: null, isPending: false, isError: false };
  mocks.connectivity = { state: "connected", refresh: vi.fn() };
  mocks.navigate.mockReset();
});

afterEach(() => cleanup());

describe("HomePage", () => {
  it("explains only the existing prepare, review, schedule, and publish workflow", () => {
    renderHome();

    expectJourneyVisible();
    expect(
      screen.getByRole("link", { name: "Create your account" }),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeTruthy();
    expect(screen.getByText(/00:00 UTC/)).toBeTruthy();
    expect(screen.queryByText(/search|rankings?|votes?|comments?/i)).toBeNull();
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

    expectJourneyVisible();
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

      expectJourneyVisible();
      expect(screen.queryByRole("alert")).toBeNull();
    },
  );

  it("shows a recovery action during an outage and clears it after recovery", () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    mocks.connectivity = { state: "unavailable", refresh };
    const view = renderHome();

    expectJourneyVisible();
    expect(screen.getByRole("alert").textContent).toContain(
      "temporarily unavailable",
    );
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(refresh).toHaveBeenCalledOnce();

    mocks.connectivity = { state: "connected", refresh };
    view.rerender(<HomePage identityClient={identityClient} />);
    expectJourneyVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
