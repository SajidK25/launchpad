/** @vitest-environment jsdom */

import { describe, expect, it, vi } from "vitest";

import { createProfileClient, ProfileRequestError } from "./client";

describe("profile client", () => {
  it("uses the current session and CSRF token for an R2 photo transfer", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    const ensureSession = vi.fn().mockResolvedValue(undefined);
    const client = createProfileClient(
      fetcher,
      () => "csrf-now",
      ensureSession,
    );
    const file = new File(["photo"], "photo.png", { type: "image/png" });

    await client.uploadPhoto(
      {
        upload_id: "upload-1",
        upload_url: "/api/v1/me/profile/photo-uploads/upload-1/content",
        fields: {},
        expires_in: 300,
        upload_method: "PUT",
        upload_transport: "authenticated_api",
        upload_headers: { "Content-Type": "image/png" },
      },
      file,
    );

    expect(ensureSession).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/me/profile/photo-uploads/upload-1/content",
      expect.objectContaining({
        method: "PUT",
        credentials: "include",
        headers: {
          "Content-Type": "image/png",
          "X-CSRF-Token": "csrf-now",
        },
        body: file,
      }),
    );
  });

  it("uses the generated GraphQL operation for public profiles", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { publicProfile: null } }), {
        status: 200,
      }),
    );
    const client = createProfileClient(fetcher);

    await expect(client.fetchPublicProfile("account")).resolves.toEqual(null);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/graphql",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });

  it("sends profile edits with credentials, CSRF, and generated request fields", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          account_id: "account",
          display_name: null,
          bio: "Draft",
          links: [],
          photo_url: null,
          visibility: "private",
          published_at: null,
          version: 2,
          became_private: true,
        }),
        { status: 200 },
      ),
    );
    const client = createProfileClient(fetcher, () => "csrf-2");

    await client.updateProfile({ version: 1, bio: "Draft" });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/me/profile",
      expect.objectContaining({
        method: "PATCH",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": "csrf-2",
        },
      }),
    );
  });

  it("normalizes malformed GraphQL responses", async () => {
    const client = createProfileClient(
      vi
        .fn()
        .mockResolvedValue(
          new Response("<html>bad gateway</html>", { status: 502 }),
        ),
    );
    await expect(client.fetchPublicProfile("account")).rejects.toBeInstanceOf(
      ProfileRequestError,
    );
  });
});
