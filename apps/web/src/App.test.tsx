/** @vitest-environment jsdom */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { useConnectivity } from "./connectivity/useConnectivity";
import { createIdentityClient } from "./identity/client";

vi.mock("./identity/Screens", () => ({
  IdentityRoutes: () => <div>identity routes</div>,
}));
vi.mock("./profiles/ProfileScreens", () => ({
  ProfileRoutes: () => <div>profile routes</div>,
}));
vi.mock("./identity/client", () => ({
  createIdentityClient: vi.fn(() => ({ getCsrfToken: () => null })),
}));

vi.mock("./connectivity/useConnectivity", () => ({
  useConnectivity: vi.fn(),
}));

const mockedUseConnectivity = vi.mocked(useConnectivity);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
  vi.clearAllMocks();
});

describe("App", () => {
  it.each([
    ["loading", "Checking connection"],
    ["connected", "Connected"],
    ["unavailable", "Unavailable"],
  ] as const)(
    "presents %s without implying a different state",
    (state, status) => {
      mockedUseConnectivity.mockReturnValue({ refresh: vi.fn(), state });

      render(<App />);

      expect(screen.getByRole("status").textContent).toContain(status);
      expect(screen.getByRole("heading", { name: "Launchpad" })).not.toBeNull();
    },
  );

  it("announces unavailable state and lets keyboard users retry", () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    mockedUseConnectivity.mockReturnValue({ refresh, state: "unavailable" });

    render(<App />);

    const status = screen.getByRole("status");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.getAttribute("aria-atomic")).toBe("true");

    const retry = screen.getByRole("button", { name: "Check again" });
    retry.focus();
    expect(document.activeElement).toBe(retry);
    fireEvent.click(retry);

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("keeps the identity client stable across route rerenders", () => {
    mockedUseConnectivity.mockReturnValue({
      refresh: vi.fn(),
      state: "connected",
    });
    window.history.pushState({}, "", "/signin");
    const view = render(<App />);

    expect(createIdentityClient).toHaveBeenCalledTimes(1);
    window.history.pushState({}, "", "/profile");
    window.dispatchEvent(new PopStateEvent("popstate"));
    view.rerender(<App />);

    expect(createIdentityClient).toHaveBeenCalledTimes(1);
  });
});
