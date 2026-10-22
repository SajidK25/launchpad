/** @vitest-environment jsdom */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { useConnectivity } from "./connectivity/useConnectivity";
import { createIdentityClient } from "./identity/client";
import { createProductClient } from "./products/client";

const mocks = vi.hoisted(() => ({
  session: null as unknown,
  logout: { isPending: false, mutateAsync: vi.fn() },
  connectivity: null as unknown,
  identityClient: { getCsrfToken: () => "stable-csrf" },
  productClient: {},
  createIdentityClient: vi.fn(),
  createProductClient: vi.fn(),
  receivedIdentityClient: null as unknown,
  receivedProductClient: null as unknown,
  productFailure: false,
}));

vi.mock("./identity/client", () => ({
  createIdentityClient: mocks.createIdentityClient,
}));
vi.mock("./products/client", () => ({
  createProductClient: mocks.createProductClient,
}));
vi.mock("./identity/useIdentity", () => ({
  useCurrentSession: () => mocks.session,
  useLogout: () => mocks.logout,
}));
vi.mock("./connectivity/useConnectivity", () => ({
  useConnectivity: vi.fn(() => mocks.connectivity),
}));
vi.mock("./identity/Screens", () => ({
  IdentityRoutes: () => <div>identity routes</div>,
}));
vi.mock("./profiles/ProfileScreens", () => ({
  ProfileRoutes: () => <div>profile routes</div>,
}));
vi.mock("./products/ProductScreens", () => ({
  ProductRoutes: ({
    path,
    identityClient,
    client,
  }: {
    path: string;
    identityClient: unknown;
    client: unknown;
  }) => {
    mocks.receivedIdentityClient = identityClient;
    mocks.receivedProductClient = client;
    if (mocks.productFailure) return <BrokenProductRoute />;
    return (
      <main id="product-main" tabIndex={-1}>
        product route: {path}
        {path.startsWith("/products/review") ? (
          <h2 id="approved-reviews-title">Decision history content</h2>
        ) : null}
      </main>
    );
  },
}));
vi.mock("./notifications/NotificationBell", () => ({
  NotificationBell: () => <button type="button">Mock notifications</button>,
}));
vi.mock("./launches/LaunchScreens", () => ({
  LaunchRoutes: () => <div>launch routes</div>,
  PublicLaunchPage: ({ productId }: { productId: string }) => (
    <div>public launch: {productId}</div>
  ),
}));
vi.mock("./launches/LaunchDiscovery", () => ({
  LaunchDiscovery: () => (
    <section aria-label="Today's launches">launch discovery</section>
  ),
}));

function BrokenProductRoute(): never {
  throw new Error("private product details and stack trace");
}

const mockedUseConnectivity = vi.mocked(useConnectivity);
const mockedCreateIdentityClient = vi.mocked(createIdentityClient);
const mockedCreateProductClient = vi.mocked(createProductClient);

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

function setPath(path: string, state: Record<string, unknown> = {}) {
  window.history.pushState(state, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

beforeEach(() => {
  mocks.session = memberSession();
  mocks.logout = {
    isPending: false,
    mutateAsync: vi.fn().mockResolvedValue(undefined),
  };
  mocks.connectivity = { refresh: vi.fn(), state: "connected" };
  mocks.identityClient = { getCsrfToken: () => "stable-csrf" };
  mocks.productClient = {};
  mocks.receivedIdentityClient = null;
  mocks.receivedProductClient = null;
  mocks.productFailure = false;
  mockedCreateIdentityClient
    .mockReset()
    .mockReturnValue(mocks.identityClient as never);
  mockedCreateProductClient
    .mockReset()
    .mockReturnValue(mocks.productClient as never);
  mockedUseConnectivity.mockClear();
  window.history.pushState({}, "", "/");
});

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
  vi.restoreAllMocks();
});

describe("App", () => {
  it("shows the public landing page and confines connectivity state to its outage message", () => {
    mocks.session = { data: null, isPending: false, isError: false };
    mockedUseConnectivity.mockReturnValue({
      refresh: vi.fn(),
      state: "unavailable",
    });

    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Fresh products. Every day." }),
    ).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain(
      "temporarily unavailable",
    );
    expect(
      screen.getByRole("link", { name: "Create your account" }),
    ).toBeTruthy();
    expect(mockedUseConnectivity).toHaveBeenCalledOnce();
  });

  it("routes account and public product surfaces through the public shell", () => {
    window.history.pushState({}, "", "/signin");
    const view = render(<App />);

    expect(
      screen.getByRole("navigation", { name: "Public navigation" }),
    ).toBeTruthy();
    expect(screen.getByText("identity routes")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Your products" })).toBeNull();

    setPath("/launches/product-1");
    view.rerender(<App />);
    expect(screen.getByText("public launch: product-1")).toBeTruthy();
    expect(
      screen.getByRole("navigation", { name: "Public navigation" }),
    ).toBeTruthy();
  });

  it("routes founder and reviewer work through role-specific workspace shells", () => {
    window.history.pushState({}, "", "/products/product-1");
    const view = render(<App />);

    expect(screen.getByText("product route: /products/product-1")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Your products" })).toBeTruthy();
    expect(
      screen.getAllByRole("button", { name: "Mock notifications" }),
    ).toHaveLength(1);

    mocks.session = memberSession("reviewer");
    setPath("/products/review");
    view.rerender(<App />);
    expect(screen.getByText("product route: /products/review")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Review queue" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Decision history" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Your products" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Mock notifications" }),
    ).toBeNull();
  });

  it("scrolls a same-route decision-history link to its content", () => {
    mocks.session = memberSession("reviewer");
    window.history.pushState({}, "", "/products/review");
    render(<App />);
    const target = document.getElementById("approved-reviews-title");
    const scrollIntoView = vi.fn();
    if (!target) throw new Error("Decision history target missing");
    target.scrollIntoView = scrollIntoView;

    fireEvent.click(screen.getByRole("link", { name: "Decision history" }));

    expect(scrollIntoView).toHaveBeenCalledOnce();
    expect(window.location.hash).toBe("#approved-reviews-title");
  });

  it("keeps identity and product clients stable and passes those same instances to feature routes", () => {
    window.history.pushState({}, "", "/products");
    const view = render(<App />);
    const identityClient = mocks.identityClient;
    const productClient = mocks.productClient;

    expect(mockedCreateIdentityClient).toHaveBeenCalledOnce();
    expect(mockedCreateProductClient).toHaveBeenCalledOnce();
    expect(mocks.receivedIdentityClient).toBe(identityClient);
    expect(mocks.receivedProductClient).toBe(productClient);

    setPath("/profile");
    view.rerender(<App />);
    expect(mockedCreateIdentityClient).toHaveBeenCalledOnce();
    expect(mockedCreateProductClient).toHaveBeenCalledOnce();
    expect(mocks.identityClient).toBe(identityClient);
  });

  it("moves focus to the product main landmark and clears the one-time history state", () => {
    window.history.pushState({}, "", "/products");
    const view = render(<App />);

    setPath("/products/product-1", { focusProductMain: true });
    view.rerender(<App />);

    expect(document.activeElement?.id).toBe("product-main");
    expect(window.history.state).toEqual({});
  });

  it("does not run the homepage readiness query on non-home routes", async () => {
    window.history.pushState({}, "", "/profile");
    const view = render(<App />);
    expect(mockedUseConnectivity).not.toHaveBeenCalled();

    setPath("/");
    await waitFor(() => expect(mockedUseConnectivity).toHaveBeenCalledOnce());
    view.unmount();
  });

  it("shows a safe route fallback for malformed or unsupported paths", () => {
    window.history.pushState({}, "", "/public/%ZZ");
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "This page isn’t available" }),
    ).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Your products" })).toBeNull();
    expect(
      screen.getByRole("link", { name: "Go to home" }).getAttribute("href"),
    ).toBe("/");
  });

  it("replaces failed descendant content with the privacy-safe render fallback", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    mocks.productFailure = true;
    window.history.pushState({}, "", "/products");

    render(<App />);

    expect(
      screen.getByRole("heading", { name: "This page hit a snag" }),
    ).toBeTruthy();
    expect(screen.queryByText(/private product details/i)).toBeNull();
    expect(document.body.textContent).not.toContain(
      "private product details and stack trace",
    );
  });
});
