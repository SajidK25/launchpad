/** @vitest-environment jsdom */

import {
  act,
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
  createLaunchClient: vi.fn(),
  launchClient: {},
  receivedIdentityClient: null as unknown,
  receivedProductClient: null as unknown,
  productFailure: false,
  archiveDate: null as string | null,
  discoverState: null as null | { search: string; topicIds: string[] },
  discoverCallbacks: null as null | {
    search: (value: string) => void;
    topics: (value: string[]) => void;
  },
  receivedVoteReviewIdentityClient: null as unknown,
}));

vi.mock("./identity/client", () => ({
  createIdentityClient: mocks.createIdentityClient,
}));
vi.mock("./products/client", () => ({
  createProductClient: mocks.createProductClient,
}));
vi.mock("./launches/client", () => ({
  createLaunchClient: mocks.createLaunchClient,
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
  PublicLaunchArchive: ({ date }: { date: string }) => {
    mocks.archiveDate = date;
    return <div>public archive: {date}</div>;
  },
  PublicLaunchPage: ({ productId }: { productId: string }) => (
    <div>public launch: {productId}</div>
  ),
}));
vi.mock("./launches/DiscoverPage", () => ({
  DiscoverPage: ({
    initialSearch,
    initialTopicIds,
    onSearchChange,
    onTopicIdsChange,
  }: {
    initialSearch: string;
    initialTopicIds: string[];
    onSearchChange: (value: string) => void;
    onTopicIdsChange: (value: string[]) => void;
  }) => {
    mocks.discoverState = { search: initialSearch, topicIds: initialTopicIds };
    mocks.discoverCallbacks = {
      search: onSearchChange,
      topics: onTopicIdsChange,
    };
    return (
      <section aria-label="Discover test page">
        <output>{initialSearch}</output>
        {initialTopicIds.map((id) => (
          <output key={id}>{id}</output>
        ))}
      </section>
    );
  },
}));
vi.mock("./votes/ReviewQueue", () => ({
  VoteReviewQueue: ({ identityClient }: { identityClient: unknown }) => {
    mocks.receivedVoteReviewIdentityClient = identityClient;
    return <div>vote review queue</div>;
  },
}));
vi.mock("./launches/LaunchDiscovery", () => ({
  LaunchDiscovery: ({
    onDateChange,
    headingLevel = "h2",
  }: {
    onDateChange: (date: string) => void;
    headingLevel?: "h1" | "h2";
  }) => {
    const Heading = headingLevel;
    return (
      <section aria-labelledby="mock-launch-discovery-title">
        <Heading id="mock-launch-discovery-title">Today’s launches</Heading>
        launch discovery
        <button onClick={() => onDateChange("2026-10-20")} type="button">
          Choose archive date
        </button>
      </section>
    );
  },
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
  mocks.archiveDate = null;
  mocks.discoverState = null;
  mocks.discoverCallbacks = null;
  mockedCreateIdentityClient
    .mockReset()
    .mockReturnValue(mocks.identityClient as never);
  mockedCreateProductClient
    .mockReset()
    .mockReturnValue(mocks.productClient as never);
  mocks.createLaunchClient.mockReset().mockReturnValue(mocks.launchClient);
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
      screen.getByRole("heading", {
        level: 1,
        name: "Today’s launches",
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "Take your product from ready to released.",
      }),
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

  it("renders direct archive loads in the public shell and preserves launch routes", async () => {
    window.history.pushState({}, "", "/launches/archive/2026-10-20");
    const view = render(<App />);

    expect(screen.getByText("public archive: 2026-10-20")).toBeTruthy();
    expect(mocks.archiveDate).toBe("2026-10-20");
    expect(
      screen.getByRole("navigation", { name: "Public navigation" }),
    ).toBeTruthy();

    setPath("/launches");
    await waitFor(() => expect(screen.getByText("launch routes")).toBeTruthy());

    setPath("/launches/product-1");
    await waitFor(() =>
      expect(screen.getByText("public launch: product-1")).toBeTruthy(),
    );
    view.unmount();
  });

  it("restores Discover filters from URL and writes search and topic changes to history", () => {
    window.history.pushState(
      {},
      "",
      "/discover?q=maker&topic=topic-b&topic=topic-a",
    );
    render(<App />);

    expect(mocks.discoverState).toEqual({
      search: "maker",
      topicIds: ["topic-b", "topic-a"],
    });
    const previousLength = window.history.length;
    act(() => mocks.discoverCallbacks?.search("maker tools"));
    expect(window.location.search).toContain("q=maker+tools");
    expect(window.location.search).toContain("topic=topic-b&topic=topic-a");
    expect(window.history.length).toBe(previousLength);

    act(() => mocks.discoverCallbacks?.topics(["topic-c"]));
    expect(window.location.search).toContain("topic=topic-c");
    expect(mocks.discoverState?.topicIds).toEqual(["topic-c"]);
  });

  it("moves focus into the public page after choosing an archive date from home", async () => {
    window.history.pushState({}, "", "/");
    render(<App />);

    fireEvent.click(
      screen.getByRole("button", { name: "Choose archive date" }),
    );

    await waitFor(() =>
      expect(screen.getByRole("main").id).toBe("main-content"),
    );
    expect(document.activeElement).toBe(screen.getByRole("main"));
    expect(window.location.pathname).toBe("/launches/archive/2026-10-20");
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

  it("mounts the vote-review queue in the reviewer workspace", () => {
    mocks.session = memberSession("reviewer");
    window.history.pushState({}, "", "/votes/reviews");
    render(<App />);

    expect(screen.getByText("vote review queue")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Vote flags" })).toBeTruthy();
    expect(mocks.receivedVoteReviewIdentityClient).toBe(mocks.identityClient);
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
