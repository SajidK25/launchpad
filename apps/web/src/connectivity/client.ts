import type { paths } from "@launchpad/contracts";

export const CONNECTIVITY_TIMEOUT_MS = 3_500;

type ReadinessResponse =
  paths["/api/v1/health/ready"]["get"]["responses"]["200"]["content"]["application/json"];

export type Fetcher = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export class ConnectivityRequestError extends Error {
  constructor() {
    super("The readiness request did not return a valid ready response.");
  }
}

export async function fetchReadiness(
  fetcher?: Fetcher,
): Promise<ReadinessResponse> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), CONNECTIVITY_TIMEOUT_MS);

  try {
    const request = fetcher ?? globalThis.fetch.bind(globalThis);
    const response = await request("/api/v1/health/ready", {
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new ConnectivityRequestError();
    }

    const body: unknown = await response.json();
    if (!isReadyResponse(body)) {
      throw new ConnectivityRequestError();
    }

    return body;
  } catch (error) {
    if (error instanceof ConnectivityRequestError) {
      throw error;
    }
    throw new ConnectivityRequestError();
  } finally {
    clearTimeout(timeout);
  }
}

function isReadyResponse(body: unknown): body is ReadinessResponse {
  return (
    typeof body === "object" &&
    body !== null &&
    "status" in body &&
    body.status === "ready"
  );
}
