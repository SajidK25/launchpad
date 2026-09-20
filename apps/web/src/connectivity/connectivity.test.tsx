/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CONNECTIVITY_TIMEOUT_MS,
  ConnectivityRequestError,
  fetchReadiness,
} from "./client";
import { useConnectivity } from "./useConnectivity";

function queryWrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("fetchReadiness", () => {
  it("accepts only a valid ready response", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ status: "ready" }), { status: 200 }),
      );

    await expect(fetchReadiness(fetcher)).resolves.toEqual({ status: "ready" });
  });

  it("rejects unavailable, failed, and malformed responses", async () => {
    await expect(
      fetchReadiness(
        vi.fn().mockResolvedValue(new Response(null, { status: 503 })),
      ),
    ).rejects.toBeInstanceOf(ConnectivityRequestError);
    await expect(
      fetchReadiness(vi.fn().mockRejectedValue(new Error("network"))),
    ).rejects.toBeInstanceOf(ConnectivityRequestError);
    await expect(
      fetchReadiness(
        vi
          .fn()
          .mockResolvedValue(new Response(JSON.stringify({ status: "alive" }))),
      ),
    ).rejects.toBeInstanceOf(ConnectivityRequestError);
  });

  it("aborts an unresponsive request after the bounded client timeout", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    );

    const request = fetchReadiness(fetcher);
    const rejection = expect(request).rejects.toBeInstanceOf(
      ConnectivityRequestError,
    );
    await vi.advanceTimersByTimeAsync(CONNECTIVITY_TIMEOUT_MS);

    await rejection;
  });
});

describe("useConnectivity", () => {
  it("never reports connected before the initial request resolves", () => {
    const fetcher = vi.fn(() => new Promise<Response>(() => undefined));

    const { result } = renderHook(() => useConnectivity(fetcher), {
      wrapper: queryWrapper,
    });

    expect(result.current.state).toBe("loading");
  });

  it("reports connected only after a fresh valid ready response", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ status: "ready" }), { status: 200 }),
      );

    const { result } = renderHook(() => useConnectivity(fetcher), {
      wrapper: queryWrapper,
    });

    await waitFor(() => expect(result.current.state).toBe("connected"));
  });

  it("replaces a prior success with unavailable after a fresh failure", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ready" }), { status: 200 }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 503 }));

    const { result } = renderHook(() => useConnectivity(fetcher), {
      wrapper: queryWrapper,
    });
    await waitFor(() => expect(result.current.state).toBe("connected"));

    await act(async () => {
      await result.current.refresh();
    });

    await waitFor(() => expect(result.current.state).toBe("unavailable"));
  });

  it("recovers after an explicit refresh receives a valid ready response", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ready" }), { status: 200 }),
      );

    const { result } = renderHook(() => useConnectivity(fetcher), {
      wrapper: queryWrapper,
    });
    await waitFor(() => expect(result.current.state).toBe("unavailable"));

    await act(async () => {
      await result.current.refresh();
    });

    await waitFor(() => expect(result.current.state).toBe("connected"));
  });
});
