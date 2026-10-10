/** @vitest-environment jsdom */

import { describe, expect, it, vi } from "vitest";
import type { components } from "@launchpad/contracts";

import { createUploadClient, UploadRequestError } from "./client";

describe("shared upload client", () => {
  it("uses generated transport fields for both upload intent responses", () => {
    const profileIntent = {
      upload_id: "profile-upload",
      upload_url: "/api/v1/me/profile/photo-uploads/profile-upload/content",
      fields: {},
      expires_in: 300,
      upload_method: "PUT",
      upload_transport: "authenticated_api",
      upload_headers: { "Content-Type": "image/png" },
    } satisfies components["schemas"]["PhotoUploadResponse"];
    const productIntent = {
      asset_id: "product-asset",
      upload_url: "/api/v1/me/products/product/assets/product-asset/content",
      fields: {},
      expires_in: 300,
      upload_method: "PUT",
      upload_transport: "authenticated_api",
      upload_headers: { "Content-Type": "image/png" },
    } satisfies components["schemas"]["ProductAssetIntentResponse"];

    expect(profileIntent.upload_method).toBe("PUT");
    expect(productIntent.upload_transport).toBe("authenticated_api");
  });

  it("submits MinIO form fields without browser credentials", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    const identity = {
      ensureSession: vi.fn(),
      getCsrfToken: vi.fn().mockReturnValue("csrf-current"),
    };
    const file = new File(["image bytes"], "logo.png", { type: "image/png" });
    const uploader = createUploadClient(fetcher, identity);

    await uploader.upload(
      {
        upload_url: "http://minio:9000/private",
        fields: { key: "profile-staging/id", "Content-Type": "image/png" },
        upload_method: "POST",
        upload_transport: "storage_form",
        upload_headers: {},
      },
      file,
    );

    const init = fetcher.mock.calls[0]?.[1] as RequestInit;
    const form = init.body as FormData;
    expect(fetcher).toHaveBeenCalledWith(
      "http://minio:9000/private",
      expect.objectContaining({ method: "POST", credentials: "omit" }),
    );
    expect(form.get("key")).toBe("profile-staging/id");
    expect(form.get("Content-Type")).toBe("image/png");
    expect(form.get("file")).toBe(file);
    expect(identity.ensureSession).not.toHaveBeenCalled();
    expect(identity.getCsrfToken).not.toHaveBeenCalled();
  });

  it("sends authenticated API bytes with the current CSRF token", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    const identity = {
      ensureSession: vi.fn().mockResolvedValue(undefined),
      getCsrfToken: vi.fn().mockReturnValue("csrf-live"),
    };
    const file = new File(["image bytes"], "avatar.png", { type: "image/png" });
    const uploader = createUploadClient(fetcher, identity);
    const instruction = {
      upload_url: "/api/v1/me/profile/photo-uploads/id/content",
      fields: {},
      upload_method: "PUT",
      upload_transport: "authenticated_api",
      upload_headers: { "Content-Type": "image/png" },
    } as const;

    await uploader.upload(instruction, file);

    expect(identity.ensureSession).toHaveBeenCalledOnce();
    expect(identity.getCsrfToken).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith(
      instruction.upload_url,
      expect.objectContaining({
        method: "PUT",
        credentials: "include",
        headers: {
          "Content-Type": "image/png",
          "X-CSRF-Token": "csrf-live",
        },
        body: file,
      }),
    );
  });

  it("rejects a cross-origin API instruction before session lookup or fetch", async () => {
    const fetcher = vi.fn();
    const identity = {
      ensureSession: vi.fn(),
      getCsrfToken: vi.fn().mockReturnValue("csrf-live"),
    };
    const uploader = createUploadClient(fetcher, identity);
    const file = new File(["image bytes"], "avatar.png", { type: "image/png" });

    await expect(
      uploader.upload(
        {
          upload_url: "https://uploads.attacker.test/api/v1/content",
          fields: {},
          upload_method: "PUT",
          upload_transport: "authenticated_api",
          upload_headers: { "Content-Type": "image/png" },
        },
        file,
      ),
    ).rejects.toBeInstanceOf(UploadRequestError);
    expect(fetcher).not.toHaveBeenCalled();
    expect(identity.ensureSession).not.toHaveBeenCalled();
  });

  it("reports non-success transfer responses as typed safe errors", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response("service unavailable", { status: 503 }));
    const uploader = createUploadClient(fetcher, {
      ensureSession: vi.fn().mockResolvedValue(undefined),
      getCsrfToken: vi.fn().mockReturnValue("csrf-live"),
    });
    const file = new File(["image bytes"], "avatar.png", { type: "image/png" });

    await expect(
      uploader.upload(
        {
          upload_url: "/api/v1/me/profile/photo-uploads/id/content",
          fields: {},
          upload_method: "PUT",
          upload_transport: "authenticated_api",
          upload_headers: { "Content-Type": "image/png" },
        },
        file,
      ),
    ).rejects.toMatchObject({
      status: 503,
      body: "service unavailable",
    });
  });

  it("does not complete an upload after a failed transfer", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response("upload rejected", { status: 413 }));
    const uploader = createUploadClient(fetcher, {
      ensureSession: vi.fn().mockResolvedValue(undefined),
      getCsrfToken: vi.fn().mockReturnValue("csrf-live"),
    });
    const file = new File(["image bytes"], "avatar.png", { type: "image/png" });
    const complete = vi.fn().mockResolvedValue("completed");

    await expect(
      uploader.uploadAndComplete(
        {
          upload_url: "/api/v1/me/profile/photo-uploads/id/content",
          fields: {},
          upload_method: "PUT",
          upload_transport: "authenticated_api",
          upload_headers: { "Content-Type": "image/png" },
        },
        file,
        complete,
      ),
    ).rejects.toBeInstanceOf(UploadRequestError);
    expect(complete).not.toHaveBeenCalled();
  });
});
