/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { createIdentityClient } from "./client";
import {
  useCurrentSession,
  useLogin,
  useLogout,
  useResetPassword,
  useVerify,
} from "./useIdentity";

function wrapper(
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function response(body: unknown, status = 200) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
  });
}

describe("identity hooks", () => {
  it("loads the current session with TanStack Query", async () => {
    const client = createIdentityClient(
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            account_id: "a",
            csrf_token: "c",
            verified: false,
          }),
        ),
      ),
    );
    const { result } = renderHook(() => useCurrentSession(client), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.data?.account_id).toBe("a"));
  });

  it("clears session and profile caches after successful logout", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const client = createIdentityClient(
      vi.fn().mockResolvedValue(response(undefined, 204)),
    );
    queryClient.setQueryData(
      ["identity", "session"],
      { account_id: "a" },
      { updatedAt: 0 },
    );
    queryClient.setQueryData(["profiles", "viewer"], { accountId: "a" });
    const { result } = renderHook(() => useLogout(client), {
      wrapper: wrapper(queryClient),
    });
    await result.current.mutateAsync();
    expect(queryClient.getQueryData(["identity", "session"])).toBeUndefined();
    expect(queryClient.getQueryData(["profiles", "viewer"])).toBeUndefined();
  });

  it("clears profile caches when switching accounts on login", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const client = createIdentityClient(
      vi
        .fn()
        .mockResolvedValue(
          response({ account_id: "b", csrf_token: "c", verified: true }),
        ),
    );
    queryClient.setQueryData(["profiles", "viewer"], { accountId: "a" });
    const { result } = renderHook(() => useLogin(client), {
      wrapper: wrapper(queryClient),
    });
    await result.current.mutateAsync({
      email: "b@example.com",
      password: "password",
    });
    expect(queryClient.getQueryData(["profiles", "viewer"])).toBeUndefined();
  });

  it("invalidates session after verification and retains it after failed reset", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(
      ["identity", "session"],
      { account_id: "a" },
      { updatedAt: 0 },
    );
    const verifyClient = createIdentityClient(
      vi.fn().mockResolvedValue(response({ accepted: true }, 202)),
    );
    const verify = renderHook(() => useVerify(verifyClient), {
      wrapper: wrapper(queryClient),
    });
    await verify.result.current.mutateAsync({ token: "token" });
    expect(
      queryClient.getQueryState(["identity", "session"])?.isInvalidated,
    ).toBe(true);

    const resetClient = createIdentityClient(
      vi.fn().mockResolvedValue(response({ error: "expired" }, 400)),
    );
    const reset = renderHook(() => useResetPassword(resetClient), {
      wrapper: wrapper(queryClient),
    });
    await expect(
      reset.result.current.mutateAsync({
        token: "token",
        new_password: "password",
      }),
    ).rejects.toThrow();
    expect(queryClient.getQueryData(["identity", "session"])).toEqual({
      account_id: "a",
    });
  });

  it("removes stale session data after a revoked session response", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(
      ["identity", "session"],
      { account_id: "a" },
      { updatedAt: 0 },
    );
    const client = createIdentityClient(
      vi.fn().mockResolvedValue(response({ error: "revoked" }, 401)),
    );
    const { result } = renderHook(() => useCurrentSession(client), {
      wrapper: wrapper(queryClient),
    });
    await waitFor(() =>
      expect(queryClient.getQueryData(["identity", "session"])).toBeUndefined(),
    );
    expect(result.current.error).toBeDefined();
  });
});
