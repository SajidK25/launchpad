import { describe, expect, it, vi } from "vitest";

import { createIdentityClient } from "../identity/client";
import { createProductClient } from "./client";

describe("product client", () => {
  it("uses generated operations, credentials, and the hydrated CSRF token", async () => {
    const fetcher = vi.fn().mockImplementation(async (_url, init) => {
      if (String(_url).endsWith("/auth/session")) {
        return Response.json({
          account_id: "member-1",
          csrf_token: "csrf-current",
          role: "member",
          suspended: false,
          verified: true,
        });
      }
      if (String(_url).endsWith("/graphql")) {
        return Response.json({
          data: { viewerProducts: { items: [], nextCursor: null } },
        });
      }
      expect(init.headers).toEqual({ "X-CSRF-Token": "csrf-current" });
      return Response.json(
        { id: "p1", version: 1, status: "draft" },
        { status: 201 },
      );
    });
    const identity = createIdentityClient(fetcher);
    const client = createProductClient(fetcher, identity);

    await client.fetchViewerProducts();
    await client.createDraft();

    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "/api/v1/auth/session",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "/api/v1/graphql",
      expect.objectContaining({
        credentials: "include",
        method: "POST",
        body: expect.stringContaining("ViewerProducts"),
      }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      4,
      "/api/v1/me/products",
      expect.objectContaining({
        credentials: "include",
        method: "POST",
      }),
    );
  });

  it("does not issue a product mutation until role and suspension are hydrated", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      Response.json({
        account_id: "member-1",
        csrf_token: "csrf",
        verified: true,
      }),
    );
    const client = createProductClient(fetcher, createIdentityClient(fetcher));

    await expect(client.createDraft()).rejects.toMatchObject({ status: 200 });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/auth/session",
      expect.anything(),
    );
  });

  it("waits for current media validation and the final saved version before submit", async () => {
    const calls: string[] = [];
    const identity = createIdentityClient(
      vi.fn().mockResolvedValue(
        Response.json({
          account_id: "member-1",
          csrf_token: "csrf",
          role: "member",
          suspended: false,
          verified: true,
        }),
      ),
    );
    const client = createProductClient(
      vi.fn().mockImplementation(async (url) => {
        calls.push(String(url));
        if (String(url).endsWith("/submit"))
          return Response.json({
            product_id: "p1",
            product_version: 3,
            submission_id: "s1",
          });
        return Response.json({ id: "p1", version: 3, status: "draft" });
      }),
      identity,
    );
    let finishUpload!: () => void;
    const upload = new Promise<void>((resolve) => {
      finishUpload = resolve;
    });
    let finishSave!: () => void;
    const save = new Promise<{ version: number }>((resolve) => {
      finishSave = () => resolve({ version: 3 });
    });

    const submitting = client.submitWhenReady("p1", {
      waitForUploads: () => upload,
      saveLatest: () => save,
    });
    expect(calls).toEqual([]);
    finishUpload();
    await Promise.resolve();
    expect(calls).toEqual([]);
    finishSave();
    await submitting;
    expect(calls.at(-1)).toBe("/api/v1/me/products/p1/submit");
  });
});
