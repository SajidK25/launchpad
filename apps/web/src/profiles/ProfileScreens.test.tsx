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

import { createIdentityClient } from "../identity/client";
import { ProfileRoutes } from "./ProfileScreens";

function renderProfiles(path: string, fetcher: ReturnType<typeof vi.fn>) {
  window.history.pushState({}, "", path);
  vi.stubGlobal("fetch", fetcher);
  const client = createIdentityClient(fetcher);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ProfileRoutes identityClient={client} />
    </QueryClientProvider>,
  );
}

describe("profile screens", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows a private editor and keeps publish disabled until complete", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: {
            viewerProfile: {
              accountId: "a",
              displayName: "",
              bio: "",
              links: [],
              photoUrl: null,
              visibility: "private",
              version: 1,
            },
          },
        }),
      ),
    );
    renderProfiles("/profile", fetcher);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Publish profile" }),
      ).toBeTruthy(),
    );
    expect(
      (
        screen.getByRole("button", {
          name: "Publish profile",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(screen.getByLabelText("Display name")).toBeTruthy();
    expect(screen.queryByRole("main")).toBeNull();
  });

  it("shows field guidance for non-HTTPS links", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: {
            viewerProfile: {
              accountId: "a",
              displayName: "Member",
              bio: "Bio",
              links: [],
              photoUrl: null,
              visibility: "private",
              version: 1,
            },
          },
        }),
      ),
    );
    renderProfiles("/profile", fetcher);
    await waitFor(() =>
      expect(screen.getByLabelText(/Public HTTPS links/)).toBeTruthy(),
    );
    fireEvent.change(screen.getByLabelText(/Public HTTPS links/), {
      target: { value: "http://example.com" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save private profile" }),
    );
    expect((await screen.findByRole("alert")).textContent).toContain(
      "public HTTPS URL",
    );
  });

  it("renders only the public profile response", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: {
            publicProfile: {
              accountId: "a",
              displayName: "Public member",
              bio: "Hello",
              links: ["https://example.com"],
              photoUrl: null,
            },
          },
        }),
      ),
    );
    renderProfiles("/public/a", fetcher);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Public member" }),
      ).toBeTruthy(),
    );
    expect(screen.getByText("Hello")).toBeTruthy();
    expect(screen.queryByText(/private profile/i)).toBeNull();
  });

  it("uses the same unavailable state for private or missing public profiles", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ errors: [{ message: "Not found" }] }), {
        status: 404,
      }),
    );
    renderProfiles("/public/missing-account", fetcher);
    expect(
      await screen.findByText("This profile is private or unavailable."),
    ).toBeTruthy();
    expect(screen.queryByText(/missing-account|Not found/)).toBeNull();
  });

  it("rejects unsupported photos before any staging request", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: {
            viewerProfile: {
              accountId: "a",
              displayName: "Member",
              bio: "Bio",
              links: [],
              photoUrl: null,
              visibility: "private",
              version: 1,
            },
          },
        }),
      ),
    );
    renderProfiles("/profile", fetcher);
    const photo = await screen.findByLabelText(/Profile photo/);
    fireEvent.change(photo, {
      target: {
        files: [
          new File(["not an image"], "notes.txt", { type: "text/plain" }),
        ],
      },
    });
    expect((await screen.findByRole("alert")).textContent).toContain(
      "JPEG, PNG, or WebP",
    );
  });

  it("preserves an existing photo when saving text-only edits", async () => {
    const profile = {
      accountId: "a",
      displayName: "Member",
      bio: "Bio",
      links: ["https://example.com"],
      photoUrl: "/api/v1/profiles/a/photo",
      visibility: "private",
      version: 3,
    };
    const fetcher = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input) === "/api/v1/graphql")
          return Promise.resolve(
            new Response(JSON.stringify({ data: { viewerProfile: profile } })),
          );
        expect(init?.method).toBe("PATCH");
        return Promise.resolve(
          new Response(JSON.stringify({ ...profile, became_private: false })),
        );
      });
    renderProfiles("/profile", fetcher);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save private profile" }),
      ).toBeTruthy(),
    );
    fireEvent.change(screen.getByLabelText(/One-line bio/), {
      target: { value: "Updated bio" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save private profile" }),
    );
    await waitFor(() =>
      expect(fetcher).toHaveBeenCalledWith(
        "/api/v1/me/profile",
        expect.anything(),
      ),
    );
    const patchCall = fetcher.mock.calls.find(
      ([input]) => String(input) === "/api/v1/me/profile",
    );
    expect(JSON.parse(String(patchCall?.[1]?.body))).not.toHaveProperty(
      "photo_upload_id",
    );
  });

  it("saves a required-field removal and announces the automatic-private result", async () => {
    const profile = {
      accountId: "a",
      displayName: "Member",
      bio: "Bio",
      links: ["https://example.com"],
      photoUrl: "/api/v1/profiles/a/photo",
      visibility: "public",
      version: 4,
    };
    const fetcher = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/graphql")
        return Promise.resolve(
          new Response(JSON.stringify({ data: { viewerProfile: profile } })),
        );
      return Promise.resolve(
        new Response(
          JSON.stringify({
            account_id: "a",
            display_name: null,
            bio: "Bio",
            links: ["https://example.com"],
            photo_url: null,
            visibility: "private",
            published_at: null,
            version: 5,
            became_private: true,
          }),
        ),
      );
    });
    renderProfiles("/profile", fetcher);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save private profile" }),
      ).toBeTruthy(),
    );
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save private profile" }),
    );
    expect((await screen.findByRole("status")).textContent).toContain(
      "profile is private",
    );
  });

  it("retries a failed profile transfer with the same pending intent", async () => {
    const profile = {
      accountId: "a",
      displayName: "Member",
      bio: "Bio",
      links: [],
      photoUrl: null,
      visibility: "private",
      version: 1,
    };
    let intentCount = 0;
    let transferCount = 0;
    let completionCount = 0;
    const fetcher = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/graphql")
        return Promise.resolve(
          new Response(JSON.stringify({ data: { viewerProfile: profile } })),
        );
      if (String(input) === "/api/v1/me/profile/photo-uploads")
        intentCount += 1;
      if (String(input) === "/api/v1/me/profile/photo-uploads")
        return Promise.resolve(
          new Response(
            JSON.stringify({
              upload_id: "upload",
              upload_url: "https://staging.example/upload",
              fields: { key: "profile-staging/photo" },
              expires_in: 60,
              upload_method: "POST",
              upload_transport: "storage_form",
              upload_headers: {},
            }),
          ),
        );
      if (String(input) === "https://staging.example/upload") {
        transferCount += 1;
        return Promise.resolve(
          new Response(null, { status: transferCount === 1 ? 503 : 204 }),
        );
      }
      if (String(input).endsWith("/complete")) completionCount += 1;
      return Promise.resolve(
        new Response(
          JSON.stringify({
            upload_id: "upload",
            byte_count: 12,
            media_type: "image/png",
          }),
        ),
      );
    });
    renderProfiles("/profile", fetcher);
    const photo = await screen.findByLabelText(/Profile photo/);
    const file = new File(["valid"], "photo.png", {
      type: "image/png",
      lastModified: 123,
    });
    fireEvent.change(photo, {
      target: {
        files: [file],
      },
    });
    expect(await screen.findByRole("alert")).toBeTruthy();
    fireEvent.change(photo, { target: { files: [file] } });
    await waitFor(() =>
      expect(screen.getByText(/Photo validated/)).toBeTruthy(),
    );
    expect(screen.queryByText("https://staging.example/upload")).toBeNull();
    expect(intentCount).toBe(1);
    expect(transferCount).toBe(2);
    expect(completionCount).toBe(1);
  });
});
