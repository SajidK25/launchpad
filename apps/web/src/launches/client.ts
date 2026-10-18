import type { components } from "@launchpad/contracts";
import {
  PUBLIC_PRODUCT_QUERY,
  VIEWER_LAUNCH_BOOKINGS_QUERY,
  VIEWER_LAUNCH_NOTIFICATION_PREFERENCES_QUERY,
  type PublicProductQuery,
  type PublicProductQueryVariables,
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

export type LaunchBookingInput = Schemas["LaunchBookingInput"];
export type LaunchBookingResult = Schemas["LaunchBookingResponse"];
export type LaunchPreferences = Schemas["LaunchNotificationPreferences"];
export type LaunchBookingPage =
  ViewerLaunchBookingsQuery["viewerLaunchBookings"];
export type PublicProduct = PublicProductQuery["publicProduct"];

export class LaunchRequestError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`Launch request failed with status ${status}.`);
    this.name = "LaunchRequestError";
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
  ): Promise<T> {
    if (authenticated) await identity.ensureSession();
    const response = await fetcher("/api/v1/graphql", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variables }),
    });
    const value: unknown = await response.json().catch(() => null);
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
  };
}

export type LaunchClient = ReturnType<typeof createLaunchClient>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
