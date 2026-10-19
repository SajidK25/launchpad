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
import { LaunchRoutes, PublicLaunchPage } from "./LaunchScreens";

const mocks = vi.hoisted(() => ({
  session: null as unknown,
  products: null as unknown,
  publicProduct: null as unknown,
  bookings: null as unknown,
  preferences: null as unknown,
  bookMutation: { isPending: false, mutateAsync: vi.fn() },
  rescheduleMutation: { isPending: false, mutateAsync: vi.fn() },
  cancelMutation: { isPending: false, mutateAsync: vi.fn() },
  preferenceMutation: { isPending: false, mutateAsync: vi.fn() },
  logoutMutation: { isPending: false, mutateAsync: vi.fn() },
}));

vi.mock("../identity/useIdentity", () => ({
  useCurrentSession: () => mocks.session,
  useLogout: () => mocks.logoutMutation,
}));

vi.mock("../products/useProducts", () => ({
  useViewerProducts: () => mocks.products,
}));

vi.mock("../notifications/NotificationBell", () => ({
  NotificationBell: () => null,
}));

vi.mock("./useLaunches", () => ({
  useBookLaunch: () => mocks.bookMutation,
  useCancelLaunch: () => mocks.cancelMutation,
  useLaunchBookings: () => mocks.bookings,
  useLaunchLiveInvalidation: vi.fn(),
  useLaunchPreferences: () => mocks.preferences,
  usePublicProduct: () => mocks.publicProduct,
  useRescheduleLaunch: () => mocks.rescheduleMutation,
  useUpdateLaunchPreferences: () => mocks.preferenceMutation,
}));

function memberSession(overrides: Record<string, unknown> = {}) {
  return {
    account_id: "founder-1",
    csrf_token: "csrf",
    role: "member",
    suspended: false,
    verified: true,
    ...overrides,
  };
}

function product(overrides: Record<string, unknown> = {}) {
  return {
    id: "product-1",
    status: "approved",
    version: 12,
    name: "Launchpad demo",
    pitch: "A clear launch story",
    createdAt: "2026-10-01T00:00:00Z",
    updatedAt: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

const allPreferences = {
  reminderEmail: true,
  reminderInSite: true,
  liveEmail: true,
  liveInSite: true,
  failureEmail: true,
  failureInSite: true,
};

function renderLaunch() {
  return render(<LaunchRoutes identityClient={{} as IdentityClient} />);
}

function renderPublicLaunch(productId = "product-1") {
  return render(
    <PublicLaunchPage
      identityClient={{} as IdentityClient}
      productId={productId}
    />,
  );
}

function publicProduct(overrides: Record<string, unknown> = {}) {
  return {
    id: "product-1",
    name: "Launchpad demo",
    pitch: "A clear launch story",
    description: "A detailed description of the product for visitors.",
    websiteUrl: "https://example.com",
    launchedAt: "2026-10-16T00:00:00Z",
    logo: {
      id: "logo-1",
      kind: "logo",
      mediaType: "image/png",
      byteCount: 1024,
      url: "/public/logo.png",
    },
    screenshots: [
      {
        id: "shot-1",
        kind: "screenshot",
        mediaType: "image/png",
        byteCount: 2048,
        url: "/public/screen.png",
      },
    ],
    topics: ["Developer tools", "Productivity"],
    ...overrides,
  };
}

beforeEach(() => {
  mocks.session = { data: memberSession(), isPending: false, isError: false };
  mocks.products = {
    data: { items: [] },
    isPending: false,
    isError: false,
  };
  mocks.publicProduct = { data: undefined, isPending: false, isError: false };
  mocks.bookings = {
    data: { items: [], nextCursor: null },
    isPending: false,
    isError: false,
  };
  mocks.preferences = {
    data: allPreferences,
    isPending: false,
    isError: false,
  };
  mocks.bookMutation = {
    isPending: false,
    mutateAsync: vi.fn().mockResolvedValue({}),
  };
  mocks.rescheduleMutation = {
    isPending: false,
    mutateAsync: vi.fn().mockResolvedValue({}),
  };
  mocks.cancelMutation = {
    isPending: false,
    mutateAsync: vi.fn().mockResolvedValue({}),
  };
  mocks.preferenceMutation = {
    isPending: false,
    mutateAsync: vi.fn().mockResolvedValue(allPreferences),
  };
  mocks.logoutMutation = { isPending: false, mutateAsync: vi.fn() };
  vi.stubGlobal("crypto", { randomUUID: () => "test-idempotency-key" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("founder launch dashboard", () => {
  it("shows the empty state and six separately labelled notification choices", () => {
    renderLaunch();

    expect(
      screen.getByRole("heading", { name: "Your launch calendar" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "No approved products yet" }),
    ).toBeTruthy();
    expect(screen.getAllByRole("checkbox")).toHaveLength(6);
    expect(screen.getByRole("link", { name: "Your products" })).toBeTruthy();
    expect(screen.getByText("TWO PER FOUNDER")).toBeTruthy();
  });

  it("books an approved product with its current version and UTC date", async () => {
    mocks.products = {
      data: { items: [product()] },
      isPending: false,
      isError: false,
    };
    renderLaunch();

    const date = screen.getByLabelText(/Choose a launch day/);
    fireEvent.change(date, { target: { value: "2027-01-15" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Reserve launch date" }),
    );

    await waitFor(() =>
      expect(mocks.bookMutation.mutateAsync).toHaveBeenCalledWith({
        payload: { launch_date: "2027-01-15", expected_version: 12 },
        idempotencyKey: "test-idempotency-key",
      }),
    );
    expect(
      await screen.findByText("Launch booked for 2027-01-15 UTC."),
    ).toBeTruthy();
  });

  it("reschedules a booked product with the current version", async () => {
    mocks.products = {
      data: { items: [product({ status: "scheduled", version: 16 })] },
      isPending: false,
      isError: false,
    };
    mocks.bookings = {
      data: {
        items: [
          {
            id: "booking-1",
            productId: "product-1",
            state: "scheduled",
            productStatus: "scheduled",
            launchAt: "2026-12-01T00:00:00Z",
            failureReason: null,
            createdAt: "2026-10-01T00:00:00Z",
            closedAt: null,
          },
        ],
        nextCursor: null,
      },
      isPending: false,
      isError: false,
    };
    renderLaunch();

    fireEvent.change(screen.getByLabelText(/Choose a new launch day/), {
      target: { value: "2026-12-10" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reschedule launch" }));

    await waitFor(() =>
      expect(mocks.rescheduleMutation.mutateAsync).toHaveBeenCalledWith({
        payload: { launch_date: "2026-12-10", expected_version: 16 },
        idempotencyKey: "test-idempotency-key",
      }),
    );
    expect(screen.getByText(/December 1, 2026/)).toBeTruthy();
  });

  it("cancels a scheduled booking with the current product version", async () => {
    mocks.products = {
      data: { items: [product({ status: "scheduled", version: 21 })] },
      isPending: false,
      isError: false,
    };
    mocks.bookings = {
      data: {
        items: [
          {
            id: "booking-1",
            productId: "product-1",
            state: "scheduled",
            productStatus: "scheduled",
            launchAt: "2026-12-01T00:00:00Z",
            failureReason: null,
            createdAt: "2026-10-01T00:00:00Z",
            closedAt: null,
          },
        ],
        nextCursor: null,
      },
      isPending: false,
      isError: false,
    };
    renderLaunch();

    fireEvent.click(screen.getByRole("button", { name: "Cancel booking" }));

    await waitFor(() =>
      expect(mocks.cancelMutation.mutateAsync).toHaveBeenCalledWith({
        expectedVersion: 21,
        idempotencyKey: "test-idempotency-key",
      }),
    );
    expect(
      await screen.findByText(
        "Launch booking cancelled. The product is approved and private.",
      ),
    ).toBeTruthy();
  });

  it("shows a published state and public page link without booking controls", () => {
    mocks.products = {
      data: { items: [product({ status: "launched" })] },
      isPending: false,
      isError: false,
    };
    mocks.bookings = {
      data: {
        items: [
          {
            id: "booking-1",
            productId: "product-1",
            state: "launched",
            productStatus: "launched",
            launchAt: "2026-10-10T00:00:00Z",
            failureReason: null,
            createdAt: "2026-10-01T00:00:00Z",
            closedAt: "2026-10-10T00:00:00Z",
          },
        ],
        nextCursor: null,
      },
      isPending: false,
      isError: false,
    };
    renderLaunch();

    expect(screen.getByText(/This product is live/)).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "View public launch page" })
        .getAttribute("href"),
    ).toBe("/launches/product-1");
    expect(
      screen.queryByRole("button", { name: "Reserve launch date" }),
    ).toBeNull();
  });

  it("keeps a failed booking visible and announces the server failure", async () => {
    mocks.products = {
      data: { items: [product()] },
      isPending: false,
      isError: false,
    };
    mocks.bookMutation.mutateAsync
      .mockRejectedValueOnce(new Error("conflict"))
      .mockResolvedValueOnce({});
    renderLaunch();

    fireEvent.click(
      screen.getByRole("button", { name: "Reserve launch date" }),
    );

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Your current booking is unchanged",
    );
    expect(
      screen.getByRole("heading", { name: "Launchpad demo" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Reserve launch date" }),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Reserve launch date" }),
    );
    await waitFor(() =>
      expect(mocks.bookMutation.mutateAsync).toHaveBeenCalledTimes(2),
    );
    expect(mocks.bookMutation.mutateAsync.mock.calls[0][0].idempotencyKey).toBe(
      mocks.bookMutation.mutateAsync.mock.calls[1][0].idempotencyKey,
    );
  });

  it("explains missed-day recovery and keeps all six preferences independent", async () => {
    mocks.products = {
      data: { items: [product()] },
      isPending: false,
      isError: false,
    };
    mocks.bookings = {
      data: {
        items: [
          {
            id: "booking-1",
            productId: "product-1",
            state: "missed_day",
            productStatus: "approved",
            launchAt: "2026-10-10T00:00:00Z",
            failureReason: "missed_day",
            createdAt: "2026-10-01T00:00:00Z",
            closedAt: "2026-10-10T00:00:00Z",
          },
        ],
        nextCursor: null,
      },
      isPending: false,
      isError: false,
    };
    renderLaunch();

    expect(screen.getByText(/Missed launch day/)).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: "Email reminders" }));
    await waitFor(() =>
      expect(mocks.preferenceMutation.mutateAsync).toHaveBeenCalledWith({
        reminder_email: false,
        reminder_in_site: true,
        live_email: true,
        live_in_site: true,
        failure_email: true,
        failure_in_site: true,
      }),
    );
  });

  it("disables booking for unverified and suspended founders", () => {
    mocks.session = {
      data: memberSession({ verified: false, suspended: true }),
      isPending: false,
      isError: false,
    };
    mocks.products = {
      data: { items: [product()] },
      isPending: false,
      isError: false,
    };
    renderLaunch();

    expect(
      (
        screen.getByRole("button", {
          name: "Reserve launch date",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(screen.getByText(/Verify your email/)).toBeTruthy();
    expect(screen.getByText(/account is suspended/)).toBeTruthy();
  });

  it("offers a safe sign-in state when the session is missing", () => {
    mocks.session = { data: null, isPending: false, isError: false };
    renderLaunch();

    expect(screen.getByRole("status").textContent).toContain(
      "Sign in with a founder account",
    );
    expect(screen.getByRole("link", { name: "Sign in" })).toBeTruthy();
  });
});

describe("anonymous public launch page", () => {
  it("shows the launched public fields, media, date, and accessible website link", () => {
    mocks.publicProduct = {
      data: publicProduct(),
      isPending: false,
      isError: false,
    };
    renderPublicLaunch();

    expect(
      screen.getByRole("heading", { name: "Launchpad demo" }),
    ).toBeTruthy();
    expect(screen.getByText("A clear launch story")).toBeTruthy();
    expect(
      screen.getByText("A detailed description of the product for visitors."),
    ).toBeTruthy();
    expect(screen.getByText(/October 16, 2026 · 00:00 UTC/)).toBeTruthy();
    expect(screen.getByText("Developer tools")).toBeTruthy();
    expect(
      (
        screen.getByRole("img", {
          name: "Launchpad demo logo",
        }) as HTMLImageElement
      ).src,
    ).toContain("/public/logo.png");
    expect(
      screen.getByRole("img", { name: "Launchpad demo screenshot 1" }),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", {
          name: "Visit Launchpad demo website (opens in a new tab)",
        })
        .getAttribute("href"),
    ).toBe("https://example.com");
    expect(screen.queryByText(/review|founder|booking|account/i)).toBeNull();
  });

  it("shows a generic safe state for unpublished, missing, and unavailable products", () => {
    mocks.publicProduct = { data: null, isPending: false, isError: false };
    const view = renderPublicLaunch("approved-product-id");
    expect(
      screen.getByRole("heading", { name: "Launch not found" }),
    ).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe(
      "This launch is private or unavailable.",
    );
    expect(screen.queryByText("Launchpad demo")).toBeNull();

    mocks.publicProduct = {
      data: undefined,
      isPending: false,
      isError: true,
      error: new Error("private review feedback must not leak"),
    };
    view.rerender(
      <PublicLaunchPage
        identityClient={{} as IdentityClient}
        productId="missing-product-id"
      />,
    );
    expect(screen.getByRole("status").textContent).toBe(
      "This launch is private or unavailable.",
    );
    expect(screen.queryByText(/private review feedback/)).toBeNull();
  });

  it("announces loading and keeps keyboard focusable public links", () => {
    mocks.publicProduct = { data: undefined, isPending: true, isError: false };
    const view = renderPublicLaunch();
    expect(screen.getByRole("status").textContent).toBe(
      "Opening the public product page…",
    );

    mocks.publicProduct = {
      data: publicProduct({ logo: null, screenshots: [] }),
      isPending: false,
      isError: false,
    };
    view.rerender(
      <PublicLaunchPage
        identityClient={{} as IdentityClient}
        productId="product-1"
      />,
    );
    const websiteLink = screen.getByRole("link", {
      name: "Visit Launchpad demo website (opens in a new tab)",
    });
    websiteLink.focus();
    expect(document.activeElement).toBe(websiteLink);
    expect(screen.queryByRole("img")).toBeNull();
  });
});
