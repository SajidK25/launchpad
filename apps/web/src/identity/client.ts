import type { components, paths } from "@launchpad/contracts";

type Schemas = components["schemas"];
type Fetcher = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export class IdentityRequestError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`Identity request failed with status ${status}.`);
  }
}

type LoginResponse = Schemas["LoginResponse"];
type SessionResponse = Schemas["SessionResponse"];

export function createIdentityClient(
  fetcher: Fetcher = globalThis.fetch.bind(globalThis),
) {
  let csrfToken: string | null = null;

  async function request<T>(
    path: string,
    method: "GET" | "POST",
    body?: unknown,
    unsafe = true,
  ): Promise<T> {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (unsafe && csrfToken !== null) headers["X-CSRF-Token"] = csrfToken;
    const response = await fetcher(path, {
      method,
      credentials: "include",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const responseBody = await safeJson(response);
      throw new IdentityRequestError(response.status, responseBody);
    }
    if (response.status === 204) return undefined as T;
    const responseBody = await safeJson(response);
    if (!isRecord(responseBody)) {
      throw new IdentityRequestError(response.status, responseBody);
    }
    return responseBody as T;
  }

  return {
    getCsrfToken: () => csrfToken,
    setCsrfToken: (value: string | null) => {
      csrfToken = value;
    },
    register: (payload: Schemas["EmailPasswordRequest"]) =>
      request<Schemas["AcceptedResponse"]>(
        "/api/v1/auth/register",
        "POST",
        payload,
        false,
      ),
    login: async (
      payload: Schemas["EmailPasswordRequest"],
    ): Promise<LoginResponse> => {
      const result = await request<LoginResponse>(
        "/api/v1/auth/login",
        "POST",
        payload,
        false,
      );
      if (!isLoginResponse(result)) throw new IdentityRequestError(200, result);
      csrfToken = result.csrf_token;
      return result;
    },
    currentSession: async (): Promise<SessionResponse> => {
      const result = await request<SessionResponse>(
        "/api/v1/auth/session",
        "GET",
        undefined,
        false,
      );
      if (!isSessionResponse(result))
        throw new IdentityRequestError(200, result);
      csrfToken = result.csrf_token;
      return result;
    },
    logout: async (): Promise<void> => {
      await request<void>("/api/v1/auth/logout", "POST");
      csrfToken = null;
    },
    requestVerification: () =>
      request<Schemas["AcceptedResponse"]>(
        "/api/v1/auth/verification-requests",
        "POST",
      ),
    verify: (payload: Schemas["TokenRequest"]) =>
      request<Schemas["AcceptedResponse"]>(
        "/api/v1/auth/verify",
        "POST",
        payload,
        false,
      ),
    requestPasswordReset: (email: string) =>
      request<Schemas["AcceptedResponse"]>(
        "/api/v1/auth/password-reset-requests",
        "POST",
        { email } satisfies Schemas["EmailRequest"],
        false,
      ),
    resetPassword: (payload: Schemas["PasswordResetRequest"]) =>
      request<void>("/api/v1/auth/password-resets", "POST", payload, false),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isLoginResponse(value: unknown): value is LoginResponse {
  return (
    isSessionResponse(value) &&
    typeof value.account_id === "string" &&
    typeof value.verified === "boolean"
  );
}

function isSessionResponse(value: unknown): value is SessionResponse {
  return (
    isRecord(value) &&
    typeof value.account_id === "string" &&
    typeof value.csrf_token === "string" &&
    typeof value.verified === "boolean"
  );
}

async function safeJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export type IdentityClient = ReturnType<typeof createIdentityClient>;
export type IdentityPaths = paths;
