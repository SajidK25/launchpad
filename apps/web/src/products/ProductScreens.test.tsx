/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { createElement } from "react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { IdentityRequestError, type IdentityClient } from "../identity/client";
import { ProductRoutes } from "./ProductScreens";
import { ProductRequestError, type ProductClient } from "./client";

const session = {
  account_id: "member-1",
  csrf_token: "csrf-1",
  verified: true,
  role: "member" as const,
  suspended: false,
};

if (!URL.createObjectURL)
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: () => "blob:product-preview",
  });

function fixture(
  initialStatus: "draft" | "submitted" = "draft",
  sessionOverrides: Partial<typeof session> = {},
  sessionError?: Error,
) {
  let version = 1;
  let productStatus = initialStatus;
  let viewerProductReadFails = false;
  const assets: Array<{
    id: string;
    kind: "logo" | "screenshot";
    mediaType: "image/png";
    byteCount: number;
    url: string;
  }> = [];
  let submittedVersion: number | undefined;
  const detail = () => ({
    summary: {
      id: "product-1",
      status: productStatus,
      version,
      name: "",
      pitch: "",
      createdAt: "2026-10-01T00:00:00Z",
      updatedAt: "2026-10-01T00:00:00Z",
    },
    description: "",
    websiteUrl: "",
    topics: [],
    assets: [...assets],
    submission:
      productStatus === "submitted"
        ? {
            id: "submission-1",
            submittedAt: "2026-10-01T00:00:00Z",
            productVersion: version,
          }
        : null,
  });
  const client = {
    fetchViewerProducts: vi
      .fn()
      .mockResolvedValue({ items: [], nextCursor: null }),
    fetchViewerProduct: vi.fn().mockImplementation(async () => {
      if (viewerProductReadFails) throw new Error("GraphQL refresh failed.");
      return detail();
    }),
    fetchTopicChoices: vi
      .fn()
      .mockResolvedValue([{ id: "topic-1", displayName: "AI Tools" }]),
    createDraft: vi
      .fn()
      .mockResolvedValue({ id: "product-2", version: 1, status: "draft" }),
    saveProduct: vi
      .fn()
      .mockImplementation(
        async (_id: string, payload: Record<string, unknown>) => {
          version += 1;
          const fields = payload;
          return { id: "product-1", ...fields, version, status: productStatus };
        },
      ),
    attachAssets: vi.fn().mockImplementation(
      async (
        _id: string,
        payload: {
          logo_asset_id: string | null;
          screenshot_asset_ids: string[];
        },
      ) => {
        assets.splice(0, assets.length);
        if (payload.logo_asset_id)
          assets.push({
            id: payload.logo_asset_id,
            kind: "logo",
            mediaType: "image/png",
            byteCount: 1200,
            url: "/private/logo",
          });
        payload.screenshot_asset_ids.forEach((id) =>
          assets.push({
            id,
            kind: "screenshot",
            mediaType: "image/png",
            byteCount: 1200,
            url: `/private/${id}`,
          }),
        );
        version += 1;
        return { id: "product-1", version, status: "draft" };
      },
    ),
    createAssetIntent: vi
      .fn()
      .mockImplementation(async (_id: string, payload: { kind: string }) => ({
        asset_id: payload.kind === "logo" ? "logo-1" : "shot-1",
        upload_url: "https://storage.example/upload",
        fields: { key: "private-test" },
        expires_in: 300,
      })),
    uploadAsset: vi.fn().mockResolvedValue(undefined),
    completeAsset: vi
      .fn()
      .mockImplementation(async (_id: string, assetId: string) => ({
        asset_id: assetId,
        kind: assetId === "logo-1" ? "logo" : "screenshot",
        media_type: "image/png",
        byte_count: 1200,
        state: "clean",
      })),
    submitWhenReady: vi.fn().mockImplementation(
      async (
        _id: string,
        readiness: {
          waitForUploads: () => Promise<unknown>;
          saveLatest: () => Promise<{ version: number }>;
        },
      ) => {
        await readiness.waitForUploads();
        submittedVersion = (await readiness.saveLatest()).version;
        productStatus = "submitted";
        return {
          product_id: "product-1",
          product_version: submittedVersion,
          submission_id: "submission-1",
        };
      },
    ),
    withdraw: vi.fn().mockImplementation(async () => {
      version += 1;
      productStatus = "draft";
      return { id: "product-1", status: productStatus, version };
    }),
    deleteDraft: vi.fn().mockResolvedValue(undefined),
  } as unknown as ProductClient;
  const identity = {
    currentSession: vi
      .fn()
      .mockImplementation(() =>
        sessionError
          ? Promise.reject(sessionError)
          : Promise.resolve({ ...session, ...sessionOverrides }),
      ),
    logout: vi.fn().mockResolvedValue(undefined),
  } as unknown as IdentityClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return {
    client,
    identity,
    submittedVersion: () => submittedVersion,
    failViewerProductRefresh() {
      viewerProductReadFails = true;
    },
    advanceServerVersion() {
      version += 1;
    },
    view(path: string) {
      return render(
        <ProductRoutes client={client} identityClient={identity} path={path} />,
        { wrapper },
      );
    },
  };
}

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

describe("founder product screens", () => {
  it.each(["/products/private-product", "/products/review"])(
    "shows the sign-in state for %s when the current session returns 401",
    async (path) => {
      const app = fixture(
        "draft",
        {},
        new IdentityRequestError(401, { detail: "not authenticated" }),
      );
      app.view(path);

      expect(
        await screen.findByRole("alert").then((alert) => alert.textContent),
      ).toContain("Sign in to view or edit your private product drafts.");
      expect(screen.getByRole("button", { name: "Sign in" })).not.toBeNull();
      expect(screen.queryByText("Checking your account…")).toBeNull();
    },
  );

  it("creates a private draft from the owner list", async () => {
    const app = fixture();
    app.view("/products");

    fireEvent.click(
      await screen.findByRole("button", { name: "Create a product draft" }),
    );

    await waitFor(() => expect(app.client.createDraft).toHaveBeenCalledOnce());
    expect(window.location.pathname).toBe("/products/product-2");
  });

  it("keeps validated uploads unattached until selected and saves before final submission", async () => {
    const app = fixture();
    app.view("/products/product-1");
    await screen.findByRole("heading", { name: "Your product" });

    fireEvent.change(screen.getByLabelText("Upload logo"), {
      target: {
        files: [new File(["logo"], "logo.png", { type: "image/png" })],
      },
    });
    fireEvent.change(screen.getByLabelText("Upload screenshot"), {
      target: {
        files: [new File(["shot"], "shot.png", { type: "image/png" })],
      },
    });
    await screen.findByText(/Validated but unattached/);
    expect(screen.getByText("One validated logo").className).toBe("incomplete");
    expect(app.client.attachAssets).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("radio"));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(
      screen.getByRole("button", { name: "Save media selection" }),
    );
    await waitFor(() =>
      expect(app.client.attachAssets).toHaveBeenCalledWith("product-1", {
        version: 1,
        logo_asset_id: "logo-1",
        screenshot_asset_ids: ["shot-1"],
      }),
    );
    await screen.findByText(
      "Selected media is attached to this private draft.",
    );

    fireEvent.change(screen.getByLabelText(/Name/), {
      target: { value: "Launchpad Studio" },
    });
    fireEvent.change(screen.getByLabelText(/One-line pitch/), {
      target: { value: "A concise product pitch" },
    });
    fireEvent.change(screen.getByLabelText(/Description/), {
      target: { value: "A complete description." },
    });
    fireEvent.change(screen.getByLabelText(/Product website/), {
      target: { value: "https://product.example" },
    });
    fireEvent.change(screen.getByLabelText(/Topics/), {
      target: { value: "AI Tools" },
    });
    app.failViewerProductRefresh();
    fireEvent.click(
      screen.getByRole("button", { name: "Submit for staff review" }),
    );

    await waitFor(() =>
      expect(app.client.submitWhenReady).toHaveBeenCalledOnce(),
    );
    expect(app.client.saveProduct).toHaveBeenCalled();
    expect(app.submittedVersion()).toBe(3);
    expect(
      await screen.findByText(
        "Your product was submitted. The latest view could not be refreshed.",
      ),
    ).not.toBeNull();
    expect(
      screen.getByRole("heading", { name: "Launchpad Studio" }),
    ).not.toBeNull();
    expect(
      screen.queryByRole("heading", { name: "Product unavailable" }),
    ).toBeNull();
  });

  it("associates required submission errors with controls and keeps the alert actionable", async () => {
    const app = fixture();
    app.view("/products/product-1");
    await screen.findByRole("heading", { name: "Your product" });
    fireEvent.click(
      screen.getByRole("button", { name: "Submit for staff review" }),
    );

    expect(
      screen.getByText("Review these field errors before continuing:")
        .textContent,
    ).toBe("Review these field errors before continuing:");
    expect(
      screen.getByText(
        "Complete the highlighted fields and submission checklist before submitting.",
      ).textContent,
    ).toBe(
      "Complete the highlighted fields and submission checklist before submitting.",
    );
    expect(screen.getByLabelText(/Name/).getAttribute("aria-invalid")).toBe(
      "true",
    );
    expect(
      screen.getByLabelText(/Name/).getAttribute("aria-describedby"),
    ).toContain("product-name-error");
    expect(document.getElementById("product-name-error")?.textContent).toBe(
      "Enter a product name.",
    );
    expect(
      screen.getByLabelText(/Product website/).getAttribute("aria-invalid"),
    ).toBe("true");
    expect(app.client.submitWhenReady).not.toHaveBeenCalled();
  });

  it("keeps an incomplete pending edit local and saves it after explicit withdrawal", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const app = fixture("submitted");
    app.view("/products/product-1");
    await screen.findByRole("heading", { name: "Your product" });

    fireEvent.change(screen.getByLabelText(/Name/), {
      target: { value: "Continue as a draft" },
    });
    await screen.findByText(/must remain complete/);
    expect(app.client.saveProduct).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: "Withdraw to private draft" }),
    );
    await waitFor(() =>
      expect(app.client.withdraw).toHaveBeenCalledWith(
        "product-1",
        "submission-1",
        1,
      ),
    );
    await waitFor(() =>
      expect(app.client.saveProduct).toHaveBeenCalledWith(
        "product-1",
        expect.objectContaining({ version: 2, name: "Continue as a draft" }),
      ),
    );
    expect(confirm).toHaveBeenCalledOnce();
    confirm.mockRestore();
  });

  it("keeps suspended founders read-only but allows pending withdrawal", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const app = fixture("submitted", { suspended: true });
    app.view("/products/product-1");
    await screen.findByRole("heading", { name: "Your product" });

    expect(
      (screen.getByLabelText(/Name/) as HTMLInputElement).matches(":disabled"),
    ).toBe(true);
    expect(
      screen.queryByRole("button", { name: "Delete private draft" }),
    ).toBeNull();
    const withdraw = screen.getByRole("button", {
      name: "Withdraw to private draft",
    });
    expect(withdraw.hasAttribute("disabled")).toBe(false);
    fireEvent.click(withdraw);
    await waitFor(() => expect(app.client.withdraw).toHaveBeenCalledOnce());
    confirm.mockRestore();
  });

  it("retains a draft and offers a retry when permanent deletion fails", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const app = fixture();
    const originalDelete = app.client.deleteDraft.bind(app.client);
    const deleteSpy = vi
      .spyOn(app.client, "deleteDraft")
      .mockRejectedValueOnce(new ProductRequestError(503, null))
      .mockImplementation(originalDelete);
    app.view("/products/product-1");
    await screen.findByRole("heading", { name: "Your product" });

    fireEvent.click(
      screen.getByRole("button", { name: "Delete private draft" }),
    );
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Deletion failed because storage is temporarily unavailable",
    );
    expect(
      screen.getByRole("heading", { name: "Your product" }),
    ).not.toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Delete private draft" }),
    );
    await waitFor(() => expect(deleteSpy).toHaveBeenCalledTimes(2));
    expect(confirm).toHaveBeenCalledTimes(2);
    confirm.mockRestore();
  });

  it("keeps invalid topic edits on screen and does not autosave them", async () => {
    const app = fixture();
    app.view("/products/product-1");
    await screen.findByRole("heading", { name: "Your product" });

    const topics = screen.getByLabelText(/Topics/);
    fireEvent.change(topics, { target: { value: "One\nTwo\nThree\nFour" } });

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Topics must be 1–3 distinct names",
    );
    expect((topics as HTMLTextAreaElement).value).toBe("One\nTwo\nThree\nFour");
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(app.client.saveProduct).not.toHaveBeenCalled();
  });

  it("announces a failed save and provides a working retry", async () => {
    const app = fixture();
    const originalSave = app.client.saveProduct.bind(app.client);
    const save = vi
      .spyOn(app.client, "saveProduct")
      .mockRejectedValueOnce(new ProductRequestError(503, null))
      .mockImplementation(originalSave);
    app.view("/products/product-1");
    await screen.findByRole("heading", { name: "Your product" });

    fireEvent.change(screen.getByLabelText(/Name/), {
      target: { value: "Retained draft" },
    });
    await screen.findByText("Not saved");
    expect(
      screen.getByRole("button", { name: "Retry saving your edits" }),
    ).not.toBeNull();
    expect((screen.getByLabelText(/Name/) as HTMLInputElement).value).toBe(
      "Retained draft",
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Retry saving your edits" }),
    );
    await screen.findByText("Saved");
    expect(save).toHaveBeenCalledTimes(2);
  });

  it("offers an explicit conflict choice and rebases local edits on the latest version", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const app = fixture();
    app.advanceServerVersion();
    const originalSave = app.client.saveProduct.bind(app.client);
    const save = vi
      .spyOn(app.client, "saveProduct")
      .mockRejectedValueOnce(new ProductRequestError(409, null))
      .mockImplementation(originalSave);
    app.view("/products/product-1");
    await screen.findByRole("heading", { name: "Your product" });

    fireEvent.change(screen.getByLabelText(/Name/), {
      target: { value: "Keep my edit" },
    });
    await screen.findByText("Needs conflict resolution");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review latest and save my displayed edits",
      }),
    );

    await screen.findByText(
      "Your displayed edits were saved over the latest version.",
    );
    expect(save).toHaveBeenLastCalledWith(
      "product-1",
      expect.objectContaining({ version: 2, name: "Keep my edit" }),
    );
    expect(confirm).toHaveBeenCalledOnce();
    confirm.mockRestore();
  });
});
