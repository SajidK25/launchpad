/** @vitest-environment jsdom */

import { describe, expect, it, vi } from "vitest";

import { classifyRoute, navigate } from "./routing";

describe("classifyRoute", () => {
  it("classifies home and account routes explicitly", () => {
    expect(classifyRoute("/")).toEqual({ type: "home" });
    expect(classifyRoute("/signin")).toEqual({
      type: "account",
      screen: "signin",
    });
    expect(classifyRoute("/register")).toEqual({
      type: "account",
      screen: "register",
    });
    expect(classifyRoute("/verify")).toEqual({
      type: "account",
      screen: "verify",
    });
    expect(classifyRoute("/recover")).toEqual({
      type: "account",
      screen: "recovery",
    });
    expect(classifyRoute("/reset")).toEqual({
      type: "account",
      screen: "reset",
    });
  });

  it("distinguishes founder and reviewer routes with review precedence", () => {
    expect(classifyRoute("/profile")).toEqual({ type: "founder-profile" });
    expect(classifyRoute("/products")).toEqual({ type: "founder-products" });
    expect(classifyRoute("/products/product-1")).toEqual({
      type: "founder-products",
      productId: "product-1",
    });
    expect(classifyRoute("/launches")).toEqual({ type: "founder-launches" });
    expect(classifyRoute("/products/review")).toEqual({
      type: "reviewer-products",
    });
    expect(classifyRoute("/products/review/product-1")).toEqual({
      type: "reviewer-products",
      productId: "product-1",
    });
  });

  it("decodes identifiers for public profile and launch routes", () => {
    expect(classifyRoute("/public/account%2Done")).toEqual({
      type: "public-profile",
      accountId: "account-one",
    });
    expect(classifyRoute("/launches/product%20one")).toEqual({
      type: "public-launch",
      productId: "product one",
    });
  });

  it("classifies real archive dates without changing existing launch routes", () => {
    expect(classifyRoute("/launches/archive/2026-10-20")).toEqual({
      type: "public-launch-archive",
      date: "2026-10-20",
    });
    expect(classifyRoute("/launches")).toEqual({ type: "founder-launches" });
    expect(classifyRoute("/launches/product-1")).toEqual({
      type: "public-launch",
      productId: "product-1",
    });
  });

  it("rejects malformed, impossible, and nested archive dates", () => {
    for (const path of [
      "/launches/archive/2026-02-30",
      "/launches/archive/2025-02-29",
      "/launches/archive/20-10-20",
      "/launches/archive/2026-10-20/extra",
    ]) {
      expect(classifyRoute(path)).toEqual({ type: "unavailable" });
    }
    expect(classifyRoute("/launches/archive/2024-02-29")).toEqual({
      type: "public-launch-archive",
      date: "2024-02-29",
    });
  });

  it("returns unavailable for malformed, incomplete, nested, and unknown paths", () => {
    expect(classifyRoute("/public/%")).toEqual({ type: "unavailable" });
    expect(classifyRoute("/public/")).toEqual({ type: "unavailable" });
    expect(classifyRoute("/products/product-1/extra")).toEqual({
      type: "unavailable",
    });
    expect(classifyRoute("/launches/product-1/extra")).toEqual({
      type: "unavailable",
    });
    expect(classifyRoute("/unknown")).toEqual({ type: "unavailable" });
    expect(classifyRoute("/constructor")).toEqual({ type: "unavailable" });
    expect(classifyRoute("/toString")).toEqual({ type: "unavailable" });
  });

  it("preserves navigation state and dispatches one popstate event", () => {
    const originalPath = window.location.pathname;
    const state = { focusProductMain: true };
    const onPopState = vi.fn();
    window.addEventListener("popstate", onPopState);

    navigate("/products/product-2", state);

    expect(window.location.pathname).toBe("/products/product-2");
    expect(window.history.state).toEqual(state);
    expect(onPopState).toHaveBeenCalledTimes(1);

    window.removeEventListener("popstate", onPopState);
    window.history.replaceState({}, "", originalPath);
  });
});
