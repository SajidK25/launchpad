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

  it("keeps a staged upload URL out of the rendered profile", async () => {
    const profile = {
      accountId: "a",
      displayName: "Member",
      bio: "Bio",
      links: [],
      photoUrl: null,
      visibility: "private",
      version: 1,
    };
    const fetcher = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/graphql")
        return Promise.resolve(
          new Response(JSON.stringify({ data: { viewerProfile: profile } })),
        );
      if (String(input) === "/api/v1/me/profile/photo-uploads")
        return Promise.resolve(
          new Response(
            JSON.stringify({
              upload_id: "upload",
              upload_url: "https://staging.example/upload",
              fields: {},
              expires_in: 60,
            }),
          ),
        );
      if (String(input) === "https://staging.example/upload")
        return Promise.resolve(new Response(null, { status: 204 }));
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
    fireEvent.change(photo, {
      target: {
        files: [new File(["valid"], "photo.png", { type: "image/png" })],
      },
    });
    await waitFor(() =>
      expect(screen.getByText(/Photo validated/)).toBeTruthy(),
    );
    expect(screen.queryByText("https://staging.example/upload")).toBeNull();
  });
});
