/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { createProfileClient, ProfileRequestError } from "./client";
import {
  useCompletePhotoUpload,
  usePublicProfile,
  usePublishProfile,
  useUpdateProfile,
} from "./useProfile";

function wrapper(
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe("profile hooks", () => {
  it("loads public profile state through TanStack Query", async () => {
    const client = createProfileClient(
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            data: {
              publicProfile: {
                accountId: "a",
                displayName: "Member",
                bio: "Bio",
                links: ["https://example.com"],
                photoUrl: null,
              },
            },
          }),
        ),
      ),
    );
    const { result } = renderHook(() => usePublicProfile(client, "a"), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.data?.accountId).toBe("a"));
  });

  it("reconciles profile queries after an edit", async () => {
    const client = createProfileClient(
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            account_id: "a",
            display_name: null,
            bio: "Draft",
            links: [],
            photo_url: null,
            visibility: "private",
            published_at: null,
            version: 2,
            became_private: false,
          }),
        ),
      ),
      () => "csrf",
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(["profiles", "viewer"], { accountId: "a" });
    queryClient.setQueryData(["profiles", "photo", "a"], new Blob());
    const { result } = renderHook(() => useUpdateProfile(client), {
      wrapper: wrapper(queryClient),
    });
    await result.current.mutateAsync({ version: 1, bio: "" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(
      queryClient.getQueryData(["profiles", "photo", "a"]),
    ).toBeUndefined();
  });

  it("reconciles privacy after publish and reports upload failures", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(["profiles", "photo", "a"], new Blob());
    const client = createProfileClient(
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            account_id: "a",
            display_name: null,
            bio: "Draft",
            links: [],
            photo_url: null,
            visibility: "private",
            published_at: null,
            version: 2,
            became_private: true,
          }),
        ),
      ),
    );
    const publish = renderHook(() => usePublishProfile(client), {
      wrapper: wrapper(queryClient),
    });
    await publish.result.current.mutateAsync(1);
    expect(
      queryClient.getQueryData(["profiles", "photo", "a"]),
    ).toBeUndefined();

    const failing = createProfileClient(
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ error: "expired" }), { status: 422 }),
        ),
    );
    const complete = renderHook(() => useCompletePhotoUpload(failing), {
      wrapper: wrapper(),
    });
    await expect(
      complete.result.current.mutateAsync("upload"),
    ).rejects.toBeInstanceOf(ProfileRequestError);
  });
});
