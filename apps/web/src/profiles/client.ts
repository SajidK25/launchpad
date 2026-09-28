import type { components } from "@launchpad/contracts";
import {
  PUBLIC_PROFILE_QUERY,
  type PublicProfileQuery,
  VIEWER_PROFILE_QUERY,
  type ViewerProfileQuery,
} from "@launchpad/contracts/src/graphql.generated";

type Schemas = components["schemas"];
type Fetcher = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export class ProfileRequestError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`Profile request failed with status ${status}.`);
  }
}

export type ProfilePatch = Schemas["ProfilePatchRequest"];

export function createProfileClient(
  fetcher: Fetcher = globalThis.fetch.bind(globalThis),
  getCsrfToken: () => string | null = () => null,
) {
  async function rest<T>(
    path: string,
    method: "PATCH" | "POST",
    body?: unknown,
  ): Promise<T> {
    const token = getCsrfToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (token !== null) headers["X-CSRF-Token"] = token;
    const response = await fetcher(path, {
      method,
      credentials: "include",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok)
      throw new ProfileRequestError(response.status, await safeJson(response));
    if (response.status === 204) return undefined as T;
    const responseBody = await safeJson(response);
    if (!isRecord(responseBody)) {
      throw new ProfileRequestError(response.status, responseBody);
    }
    return responseBody as T;
  }

  async function graphql<T>(
    query: string,
    variables?: Record<string, string>,
  ): Promise<T> {
    const response = await fetcher("/api/v1/graphql", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variables }),
    });
    const rawBody = await safeJson(response);
    if (!isRecord(rawBody)) {
      throw new ProfileRequestError(response.status, rawBody);
    }
    const body = rawBody as { data?: T; errors?: unknown[] };
    if (!response.ok || body.errors?.length || body.data === undefined) {
      throw new ProfileRequestError(response.status, body.errors ?? body);
    }
    return body.data;
  }

  return {
    fetchViewerProfile: async () => {
      const value = (await graphql<ViewerProfileQuery>(VIEWER_PROFILE_QUERY))
        .viewerProfile;
      return assertViewerProfile(value);
    },
    fetchPublicProfile: async (accountId: string) => {
      const value = (
        await graphql<PublicProfileQuery>(PUBLIC_PROFILE_QUERY, { accountId })
      ).publicProfile;
      return value === null ? null : assertPublicProfile(value);
    },
    updateProfile: async (payload: ProfilePatch) =>
      assertProfile(
        await rest<Schemas["ProfileResponse"]>(
          "/api/v1/me/profile",
          "PATCH",
          payload,
        ),
      ),
    publishProfile: async (version: number) =>
      assertProfile(
        await rest<Schemas["ProfileResponse"]>(
          "/api/v1/me/profile/publish",
          "POST",
          { version },
        ),
      ),
    unpublishProfile: async (version: number) =>
      assertProfile(
        await rest<Schemas["ProfileResponse"]>(
          "/api/v1/me/profile/unpublish",
          "POST",
          { version },
        ),
      ),
    createPhotoUpload: async (payload: Schemas["PhotoUploadRequest"]) =>
      assertPhotoUpload(
        await rest<Schemas["PhotoUploadResponse"]>(
          "/api/v1/me/profile/photo-uploads",
          "POST",
          payload,
        ),
      ),
    completePhotoUpload: async (uploadId: string) =>
      assertPhotoComplete(
        await rest<Schemas["PhotoCompleteResponse"]>(
          `/api/v1/me/profile/photo-uploads/${uploadId}/complete`,
          "POST",
        ),
      ),
    fetchPhoto: async (accountId: string): Promise<Blob> => {
      const response = await fetcher(`/api/v1/profiles/${accountId}/photo`, {
        credentials: "include",
      });
      if (!response.ok)
        throw new ProfileRequestError(
          response.status,
          await safeJson(response),
        );
      return response.blob();
    },
  };
}

function isProfileResponse(
  value: unknown,
): value is Schemas["ProfileResponse"] {
  return (
    isRecord(value) &&
    typeof value.account_id === "string" &&
    (typeof value.display_name === "string" || value.display_name === null) &&
    (typeof value.bio === "string" || value.bio === null) &&
    Array.isArray(value.links) &&
    value.links.every((link) => typeof link === "string") &&
    (typeof value.photo_url === "string" || value.photo_url === null) &&
    typeof value.visibility === "string" &&
    typeof value.version === "number" &&
    typeof value.became_private === "boolean"
  );
}

function isPhotoUploadResponse(
  value: unknown,
): value is Schemas["PhotoUploadResponse"] {
  return (
    isRecord(value) &&
    typeof value.upload_id === "string" &&
    typeof value.upload_url === "string" &&
    typeof value.expires_in === "number" &&
    isRecord(value.fields) &&
    Object.values(value.fields).every((field) => typeof field === "string")
  );
}

function isPhotoCompleteResponse(
  value: unknown,
): value is Schemas["PhotoCompleteResponse"] {
  return (
    isRecord(value) &&
    typeof value.upload_id === "string" &&
    typeof value.media_type === "string" &&
    typeof value.byte_count === "number"
  );
}

function assertProfile(value: unknown): Schemas["ProfileResponse"] {
  if (!isProfileResponse(value)) throw new ProfileRequestError(200, value);
  return value;
}

function assertViewerProfile(
  value: unknown,
): ViewerProfileQuery["viewerProfile"] {
  if (
    !isRecord(value) ||
    typeof value.accountId !== "string" ||
    typeof value.displayName !== "string" ||
    typeof value.bio !== "string" ||
    !Array.isArray(value.links) ||
    !value.links.every((link) => typeof link === "string") ||
    (typeof value.photoUrl !== "string" && value.photoUrl !== null) ||
    typeof value.visibility !== "string" ||
    typeof value.version !== "number"
  ) {
    throw new ProfileRequestError(200, value);
  }
  return value as ViewerProfileQuery["viewerProfile"];
}

function assertPublicProfile(
  value: unknown,
): PublicProfileQuery["publicProfile"] {
  if (
    !isRecord(value) ||
    typeof value.accountId !== "string" ||
    typeof value.displayName !== "string" ||
    typeof value.bio !== "string" ||
    !Array.isArray(value.links) ||
    !value.links.every((link) => typeof link === "string") ||
    (typeof value.photoUrl !== "string" && value.photoUrl !== null)
  ) {
    throw new ProfileRequestError(200, value);
  }
  return value as PublicProfileQuery["publicProfile"];
}

function assertPhotoUpload(value: unknown): Schemas["PhotoUploadResponse"] {
  if (!isPhotoUploadResponse(value)) throw new ProfileRequestError(200, value);
  return value;
}

function assertPhotoComplete(value: unknown): Schemas["PhotoCompleteResponse"] {
  if (!isPhotoCompleteResponse(value))
    throw new ProfileRequestError(200, value);
  return value;
}

async function safeJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type ProfileClient = ReturnType<typeof createProfileClient>;
