import { describe, expect, it, vi } from "vitest";

import { createIdentityClient } from "./client";

describe("identity client", () => {
  it("sends credentials and the current CSRF token for unsafe requests", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ accepted: true }), { status: 202 }),
      );
    const client = createIdentityClient(fetcher);
    client.setCsrfToken("csrf-1");

    await client.requestVerification();

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/auth/verification-requests",
      expect.objectContaining({
        credentials: "include",
        method: "POST",
        headers: { "X-CSRF-Token": "csrf-1" },
      }),
    );
  });

  it("does not update client state when CSRF is absent and the request fails", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 403 }));
    const client = createIdentityClient(fetcher);

    await expect(client.logout()).rejects.toMatchObject({ status: 403 });
    expect(client.getCsrfToken()).toBeNull();
  });
});
