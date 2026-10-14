import type { components } from "@launchpad/contracts";

type Schemas = components["schemas"];
type Identity = {
  ensureSession: () => Promise<unknown>;
  getCsrfToken: () => string | null;
};
type Fetcher = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export type UploadInstruction = Pick<
  Schemas["PhotoUploadResponse"],
  | "upload_url"
  | "fields"
  | "upload_method"
  | "upload_transport"
  | "upload_headers"
>;

export class UploadRequestError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`Upload request failed with status ${status}.`);
  }
}

export function createUploadClient(
  fetcher: Fetcher = globalThis.fetch.bind(globalThis),
  identity: Identity,
) {
  async function upload(
    instruction: UploadInstruction,
    file: File,
  ): Promise<void> {
    if (instruction.upload_transport === "storage_form") {
      if (instruction.upload_method !== "POST") throw invalidInstruction();
      const form = new FormData();
      Object.entries(instruction.fields).forEach(([key, value]) =>
        form.append(key, value),
      );
      form.append("file", file);
      await send(instruction.upload_url, {
        method: "POST",
        credentials: "omit",
        body: form,
      });
      return;
    }

    if (instruction.upload_transport !== "authenticated_api") {
      throw invalidInstruction();
    }
    if (instruction.upload_method !== "PUT") throw invalidInstruction();
    const url = requireSameOriginApiUrl(instruction.upload_url);
    const contentType = instruction.upload_headers["Content-Type"];
    if (!contentType || contentType !== file.type) throw invalidInstruction();
    if (
      Object.keys(instruction.upload_headers).some((header) =>
        ["authorization", "cookie", "host", "origin", "x-csrf-token"].includes(
          header.toLowerCase(),
        ),
      )
    ) {
      throw invalidInstruction();
    }

    await identity.ensureSession();
    const csrfToken = identity.getCsrfToken();
    if (!csrfToken) throw new UploadRequestError(401, null);
    await send(url, {
      method: "PUT",
      credentials: "include",
      headers: {
        ...instruction.upload_headers,
        "X-CSRF-Token": csrfToken,
      },
      body: file,
    });
  }

  async function uploadAndComplete<T>(
    instruction: UploadInstruction,
    file: File,
    complete: () => Promise<T>,
  ): Promise<T> {
    await upload(instruction, file);
    return complete();
  }

  async function send(url: string, init: RequestInit): Promise<void> {
    const response = await fetcher(url, init);
    if (!response.ok) {
      throw new UploadRequestError(response.status, await safeText(response));
    }
  }

  return { upload, uploadAndComplete };
}

function requireSameOriginApiUrl(value: string): string {
  const origin = globalThis.location?.origin;
  if (!origin || value.startsWith("//")) throw invalidInstruction();
  let target: URL;
  try {
    target = new URL(value, origin);
  } catch {
    throw invalidInstruction();
  }
  if (
    target.origin !== origin ||
    !target.pathname.startsWith("/api/v1/") ||
    target.username !== "" ||
    target.password !== "" ||
    target.hash !== ""
  ) {
    throw invalidInstruction();
  }
  return value;
}

function invalidInstruction(): UploadRequestError {
  return new UploadRequestError(0, null);
}

async function safeText(response: Response): Promise<string | null> {
  try {
    return (await response.text()).slice(0, 1024);
  } catch {
    return null;
  }
}
