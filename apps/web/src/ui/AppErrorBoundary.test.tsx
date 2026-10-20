/** @vitest-environment jsdom */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppErrorBoundary } from "./AppErrorBoundary";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AppErrorBoundary", () => {
  it("replaces a failed descendant with safe reload and home actions", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    function BrokenPrivateView(): never {
      throw new Error("SECRET account-id stack detail");
    }

    render(
      <AppErrorBoundary>
        <div>PRIVATE PRODUCT DATA</div>
        <BrokenPrivateView />
      </AppErrorBoundary>,
    );

    expect(screen.queryByText("PRIVATE PRODUCT DATA")).toBeNull();
    expect(
      screen.getByRole("heading", { name: "This page hit a snag" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload page" })).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Go to Launchpad home" })
        .getAttribute("href"),
    ).toBe("/");
    expect(document.body.textContent).not.toContain(
      "SECRET account-id stack detail",
    );
  });

  it("passes through healthy descendants without showing the fallback", () => {
    render(
      <AppErrorBoundary>
        <p>Product workspace</p>
      </AppErrorBoundary>,
    );

    expect(screen.getByText("Product workspace")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Reload page" })).toBeNull();
  });
});
