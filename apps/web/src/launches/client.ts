import type { components } from "@launchpad/contracts";
import {
  PUBLIC_PRODUCT_QUERY,
  DAILY_PRODUCT_RANKING_QUERY,
  PUBLIC_LAUNCHES_QUERY,
  PUBLIC_PRODUCT_CATALOG_QUERY,
  PUBLIC_CATALOG_TOPICS_QUERY,
  VIEWER_LAUNCH_BOOKINGS_QUERY,
  VIEWER_LAUNCH_NOTIFICATION_PREFERENCES_QUERY,
  type PublicProductQuery,
  type PublicProductQueryVariables,
  type DailyProductRankingQuery,
  type DailyProductRankingQueryVariables,
  type PublicLaunchesQuery,
  type PublicLaunchesQueryVariables,
  type PublicProductCatalogQuery,
  type PublicProductCatalogQueryVariables,
  type PublicCatalogTopicsQuery,
  type PublicCatalogTopicsQueryVariables,
  type ViewerLaunchBookingsQuery,
  type ViewerLaunchBookingsQueryVariables,
  type ViewerLaunchNotificationPreferencesQuery,
} from "@launchpad/contracts/src/graphql.generated";
import type { IdentityClient } from "../identity/client";

type Schemas = components["schemas"];
type Fetcher = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;
const PUBLIC_LAUNCH_REQUEST_TIMEOUT_MS = 15_000;

export type LaunchBookingInput = Schemas["LaunchBookingInput"];
export type LaunchBookingResult = Schemas["LaunchBookingResponse"];
export type LaunchPreferences = Schemas["LaunchNotificationPreferences"];
export type LaunchBookingPage =
  ViewerLaunchBookingsQuery["viewerLaunchBookings"];
export type PublicProduct = PublicProductQuery["publicProduct"];
export type DailyRankingPage = DailyProductRankingQuery["dailyProductRanking"];
export type DailyRankingItem = DailyRankingPage["items"][number];
export type PublicLaunchPage = PublicLaunchesQuery["publicLaunches"];
export type PublicCatalogPage =
  PublicProductCatalogQuery["publicProductCatalog"];
export type PublicCatalogTopicOptions =
  PublicCatalogTopicsQuery["publicCatalogTopics"];

export class LaunchRequestError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`Launch request failed with status ${status}.`);
    this.name = "LaunchRequestError";
  }
}

export class LaunchRequestTimeoutError extends Error {
  constructor() {
    super("Launch request timed out.");
    this.name = "LaunchRequestTimeoutError";
  }
}

export function createLaunchClient(
  fetcher: Fetcher = globalThis.fetch.bind(globalThis),
  identity: Pick<IdentityClient, "ensureSession" | "getCsrfToken">,
) {
  async function rest<T>(
    path: string,
    method: string,
    body?: unknown,
    extraHeaders: Record<string, string> = {},
  ): Promise<T> {
    await identity.ensureSession();
    const headers: Record<string, string> = { ...extraHeaders };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const csrf = identity.getCsrfToken();
    if (csrf !== null) headers["X-CSRF-Token"] = csrf;
    const response = await fetcher(path, {
      method,
      credentials: "include",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const value: unknown = await response.json().catch(() => null);
    if (!response.ok || !isRecord(value))
      throw new LaunchRequestError(response.status, value);
    return value as T;
  }

  async function graphql<T>(
    query: string,
    variables?: object,
    authenticated = true,
    signal?: AbortSignal,
  ): Promise<T> {
    if (authenticated) await identity.ensureSession();
    const requestController = new AbortController();
    let timedOut = false;
    const abortFromQuery = () => requestController.abort(signal?.reason);
    if (signal?.aborted) abortFromQuery();
    else signal?.addEventListener("abort", abortFromQuery, { once: true });
    const timeout = setTimeout(() => {
      timedOut = true;
      requestController.abort();
    }, PUBLIC_LAUNCH_REQUEST_TIMEOUT_MS);
    let response: Response;
    let value: unknown;
    try {
      response = await fetcher("/api/v1/graphql", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, variables }),
        signal: requestController.signal,
      });
      value = await response.json().catch((error: unknown) => {
        if (timedOut || signal?.aborted) throw error;
        return null;
      });
    } catch (error) {
      if (timedOut) throw new LaunchRequestTimeoutError();
      throw error;
    } finally {
      clearTimeout(timeout);
      signal?.removeEventListener("abort", abortFromQuery);
    }
    if (!response.ok || !isRecord(value))
      throw new LaunchRequestError(response.status, value);
    const body = value as { data?: T; errors?: unknown[] };
    if (body.errors?.length || body.data === undefined)
      throw new LaunchRequestError(response.status, body.errors ?? body);
    return body.data;
  }

  return {
    createBooking: (
      productId: string,
      payload: LaunchBookingInput,
      idempotencyKey: string,
    ): Promise<LaunchBookingResult> =>
      rest(
        `/api/v1/me/products/${encodeURIComponent(productId)}/launch-booking`,
        "POST",
        payload,
        { "Idempotency-Key": idempotencyKey },
      ),
    rescheduleBooking: (
      productId: string,
      payload: LaunchBookingInput,
      idempotencyKey: string,
    ): Promise<LaunchBookingResult> =>
      rest(
        `/api/v1/me/products/${encodeURIComponent(productId)}/launch-booking`,
        "PUT",
        payload,
        { "Idempotency-Key": idempotencyKey },
      ),
    cancelBooking: (
      productId: string,
      expectedVersion: number,
      idempotencyKey: string,
    ): Promise<LaunchBookingResult> =>
      rest(
        `/api/v1/me/products/${encodeURIComponent(productId)}/launch-booking?expected_version=${encodeURIComponent(String(expectedVersion))}`,
        "DELETE",
        undefined,
        { "Idempotency-Key": idempotencyKey },
      ),
    fetchLaunchBookings: async (
      variables: ViewerLaunchBookingsQueryVariables = {},
    ): Promise<LaunchBookingPage> =>
      (
        await graphql<ViewerLaunchBookingsQuery>(
          VIEWER_LAUNCH_BOOKINGS_QUERY,
          variables,
        )
      ).viewerLaunchBookings,
    fetchLaunchPreferences: async (): Promise<
      ViewerLaunchNotificationPreferencesQuery["viewerLaunchNotificationPreferences"]
    > =>
      (
        await graphql<ViewerLaunchNotificationPreferencesQuery>(
          VIEWER_LAUNCH_NOTIFICATION_PREFERENCES_QUERY,
        )
      ).viewerLaunchNotificationPreferences,
    updateLaunchPreferences: (
      payload: Schemas["LaunchNotificationPreferenceUpdate"],
    ): Promise<LaunchPreferences> =>
      rest("/api/v1/me/launch-notification-preferences", "PUT", payload),
    fetchPublicProduct: async (
      variables: PublicProductQueryVariables,
    ): Promise<PublicProduct> =>
      (
        await graphql<PublicProductQuery>(
          PUBLIC_PRODUCT_QUERY,
          variables,
          false,
        )
      ).publicProduct,
    fetchDailyProductRanking: async (
      variables: DailyProductRankingQueryVariables = {},
      signal?: AbortSignal,
    ): Promise<DailyRankingPage> =>
      (
        await graphql<DailyProductRankingQuery>(
          DAILY_PRODUCT_RANKING_QUERY,
          variables,
          false,
          signal,
        )
      ).dailyProductRanking,
    fetchPublicLaunches: async (
      variables: PublicLaunchesQueryVariables = {},
      signal?: AbortSignal,
    ): Promise<PublicLaunchPage> =>
      (
        await graphql<PublicLaunchesQuery>(
          PUBLIC_LAUNCHES_QUERY,
          variables,
          false,
          signal,
        )
      ).publicLaunches,
    fetchPublicCatalog: async (
      variables: PublicProductCatalogQueryVariables = {},
      signal?: AbortSignal,
    ): Promise<PublicCatalogPage> =>
      (
        await graphql<PublicProductCatalogQuery>(
          PUBLIC_PRODUCT_CATALOG_QUERY,
          variables,
          false,
          signal,
        )
      ).publicProductCatalog,
    fetchPublicCatalogTopics: async (
      variables: PublicCatalogTopicsQueryVariables = {},
      signal?: AbortSignal,
    ): Promise<PublicCatalogTopicOptions> =>
      (
        await graphql<PublicCatalogTopicsQuery>(
          PUBLIC_CATALOG_TOPICS_QUERY,
          variables,
          false,
          signal,
        )
      ).publicCatalogTopics,
  };
}

export type LaunchClient = ReturnType<typeof createLaunchClient>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
