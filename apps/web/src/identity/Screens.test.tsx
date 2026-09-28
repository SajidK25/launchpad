/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createIdentityClient } from "./client";
import { IdentityRoutes } from "./Screens";

function renderRoutes(path: string, fetcher = vi.fn()) {
  window.history.pushState({}, "", path);
  const client = createIdentityClient(fetcher);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <IdentityRoutes client={client} />
    </QueryClientProvider>,
  );
}

describe("identity screens", () => {
  afterEach(() => {
    cleanup();
  });
  it("provides labelled sign-in controls and accessible navigation", () => {
    renderRoutes("/");
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(screen.getByLabelText("Email")).toBeTruthy();
    expect(screen.getByLabelText("Password")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Create an account" }),
    ).toBeTruthy();
  });

  it("uses generic registration copy after a successful submit", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ accepted: true }), { status: 202 }),
      );
    renderRoutes("/register", fetcher);
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "member@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "long password" },
    });
    fireEvent.submit(screen.getByRole("button", { name: "Create account" }));
    expect((await screen.findByRole("status")).textContent).toContain(
      "If the address can receive Launchpad mail",
    );
  });

  it("does not enable token consumption from a GET landing page without a token", () => {
    renderRoutes("/reset");
    expect(
      (
        screen.getByRole("button", {
          name: "Set new password",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(screen.getByText(/explicitly confirm this form/)).toBeTruthy();
  });

  it("announces safe verification and resend failures", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ error: "invalid" }), { status: 400 }),
      );
    renderRoutes("/verify?token=expired", fetcher);
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm verification" }),
    );
    await waitFor(() =>
      expect(screen.getByText(/invalid or expired/)).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Send a fresh link" }));
    await waitFor(() =>
      expect(screen.getByText(/could not send a fresh link/)).toBeTruthy(),
    );
    expect(window.location.search).toBe("");
  });

  it("revokes the session on sign-out after successful sign-in", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            account_id: "a",
            csrf_token: "csrf",
            verified: true,
          }),
        ),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    renderRoutes("/signin", fetcher);
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "member@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "long password" },
    });
    fireEvent.submit(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Your private profile" }),
      ).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy(),
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("returns to sign-in after a successful reset and scrubs the token", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    renderRoutes("/reset?token=one-use", fetcher);
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "new long password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set new password" }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy(),
    );
    expect(window.location.search).toBe("");
  });
});
