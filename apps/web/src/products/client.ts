import type { components } from "@launchpad/contracts";
import {
  REVIEW_PRODUCT_QUERY,
  REVIEW_QUEUE_QUERY,
  TOPIC_CHOICES_QUERY,
  VIEWER_PRODUCT_QUERY,
  VIEWER_PRODUCTS_QUERY,
  type ReviewProductQuery,
  type ReviewProductQueryVariables,
  type ReviewQueueQuery,
  type ReviewQueueQueryVariables,
  type TopicChoicesQuery,
  type ViewerProductQuery,
  type ViewerProductQueryVariables,
  type ViewerProductsQuery,
  type ViewerProductsQueryVariables,
} from "@launchpad/contracts/src/graphql.generated";
import type { IdentityClient } from "../identity/client";

type Schemas = components["schemas"];
type Fetcher = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export class ProductRequestError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`Product request failed with status ${status}.`);
  }
}

export type ProductSave = Schemas["ProductSaveInput"];
export type ProductState = Schemas["ProductStateResponse"];
export type ProductQueuePage = ReviewQueueQuery["reviewQueue"];

export function createProductClient(
  fetcher: Fetcher = globalThis.fetch.bind(globalThis),
  identity: Pick<IdentityClient, "ensureSession" | "getCsrfToken">,
) {
  async function rest<T>(
    path: string,
    method: string,
    body?: unknown,
  ): Promise<T> {
    await identity.ensureSession();
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const token = identity.getCsrfToken();
    if (token !== null) headers["X-CSRF-Token"] = token;
    const response = await fetcher(path, {
      method,
      credentials: "include",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok)
      throw new ProductRequestError(response.status, await safeJson(response));
    if (response.status === 204) return undefined as T;
    const value = await safeJson(response);
    if (!isRecord(value)) throw new ProductRequestError(response.status, value);
    return value as T;
  }

  async function graphql<T>(query: string, variables?: object): Promise<T> {
    await identity.ensureSession();
    const response = await fetcher("/api/v1/graphql", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variables }),
    });
    const value = await safeJson(response);
    if (!isRecord(value)) throw new ProductRequestError(response.status, value);
    const body = value as { data?: T; errors?: unknown[] };
    if (!response.ok || body.errors?.length || body.data === undefined) {
      throw new ProductRequestError(response.status, body.errors ?? body);
    }
    return body.data;
  }

  return {
    fetchViewerProducts: async (variables: ViewerProductsQueryVariables = {}) =>
      (await graphql<ViewerProductsQuery>(VIEWER_PRODUCTS_QUERY, variables))
        .viewerProducts,
    fetchViewerProduct: async (variables: ViewerProductQueryVariables) =>
      (await graphql<ViewerProductQuery>(VIEWER_PRODUCT_QUERY, variables))
        .viewerProduct,
    fetchReviewQueue: async (variables: ReviewQueueQueryVariables = {}) =>
      (await graphql<ReviewQueueQuery>(REVIEW_QUEUE_QUERY, variables))
        .reviewQueue,
    fetchReviewProduct: async (variables: ReviewProductQueryVariables) =>
      (await graphql<ReviewProductQuery>(REVIEW_PRODUCT_QUERY, variables))
        .reviewProduct,
    fetchTopicChoices: async () =>
      (await graphql<TopicChoicesQuery>(TOPIC_CHOICES_QUERY)).topicChoices,
    createDraft: async () =>
      assertProductState(
        await rest<Schemas["ProductStateResponse"]>(
          "/api/v1/me/products",
          "POST",
        ),
      ),
    saveProduct: async (productId: string, payload: ProductSave) =>
      assertProductState(
        await rest<Schemas["ProductStateResponse"]>(
          `/api/v1/me/products/${encodeURIComponent(productId)}`,
          "PATCH",
          payload,
        ),
      ),
    attachAssets: async (
      productId: string,
      payload: Schemas["ProductAssetAttachmentInput"],
    ) =>
      assertProductState(
        await rest<Schemas["ProductStateResponse"]>(
          `/api/v1/me/products/${encodeURIComponent(productId)}/assets`,
          "PUT",
          payload,
        ),
      ),
    deleteDraft: (productId: string, version: number) =>
      rest<void>(
        `/api/v1/me/products/${encodeURIComponent(productId)}?expected_version=${encodeURIComponent(String(version))}`,
        "DELETE",
      ),
    createAssetIntent: (
      productId: string,
      payload: Schemas["ProductAssetIntentInput"],
    ) =>
      rest<Schemas["ProductAssetIntentResponse"]>(
        `/api/v1/me/products/${encodeURIComponent(productId)}/assets`,
        "POST",
        payload,
      ),
    completeAsset: (productId: string, assetId: string) =>
      rest<Schemas["ProductAssetCompleteResponse"]>(
        `/api/v1/me/products/${encodeURIComponent(productId)}/assets/${encodeURIComponent(assetId)}/complete`,
        "POST",
      ),
    uploadAsset: async (
      uploadUrl: string,
      fields: Record<string, string>,
      file: File,
    ) => {
      const form = new FormData();
      Object.entries(fields).forEach(([key, value]) => form.append(key, value));
      form.append("file", file);
      const response = await fetcher(uploadUrl, {
        method: "POST",
        body: form,
        credentials: "omit",
      });
      if (!response.ok)
        throw new ProductRequestError(
          response.status,
          await safeText(response),
        );
    },
    submit: async (productId: string, version: number) =>
      rest<Schemas["ProductSubmitResponse"]>(
        `/api/v1/me/products/${encodeURIComponent(productId)}/submit`,
        "POST",
        { version } satisfies Schemas["ProductVersionInput"],
      ),
    submitWhenReady: async (
      productId: string,
      readiness: {
        waitForUploads: () => Promise<unknown>;
        saveLatest: () => Promise<{ version: number }>;
      },
    ) => {
      await readiness.waitForUploads();
      const saved = await readiness.saveLatest();
      return rest<Schemas["ProductSubmitResponse"]>(
        `/api/v1/me/products/${encodeURIComponent(productId)}/submit`,
        "POST",
        { version: saved.version } satisfies Schemas["ProductVersionInput"],
      );
    },
    withdraw: (productId: string, submissionId: string, version: number) =>
      rest<Schemas["ProductStateResponse"]>(
        `/api/v1/me/products/${encodeURIComponent(productId)}/withdraw`,
        "POST",
        {
          submission_id: submissionId,
          version,
        } satisfies Schemas["ProductWithdrawInput"],
      ),
  };
}

function assertProductState(value: unknown): ProductState {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.version !== "number" ||
    (value.status !== "draft" && value.status !== "submitted")
  ) {
    throw new ProductRequestError(200, value);
  }
  return value as ProductState;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function safeJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function safeText(response: Response): Promise<string | null> {
  try {
    return await response.text();
  } catch {
    return null;
  }
}

export type ProductClient = ReturnType<typeof createProductClient>;
