/** @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, renderHook, waitFor } from "@testing-library/react";
import { createElement } from "react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { ProductClient } from "./client";
import { useProductAutosave } from "./useProducts";

function setup(client: ProductClient, debounceMs = 5) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return renderHook(
    () =>
      useProductAutosave(
        client,
        "p1",
        {
          version: 1,
          name: "Original",
          pitch: "",
          description: "",
          website_url: "",
          topic_names: [],
        },
        debounceMs,
      ),
    { wrapper },
  );
}

describe("product autosave", () => {
  it("serializes rapid edits and reports saved only after server acknowledgement", async () => {
    const saves: Array<{ version: number; name?: string | null }> = [];
    let acknowledge!: (value: {
      id: string;
      version: number;
      status: "draft";
    }) => void;
    const client = {
      saveProduct: vi.fn(
        (_: string, value: { version: number; name?: string | null }) => {
          saves.push(value);
          return new Promise<{ id: string; version: number; status: "draft" }>(
            (resolve) => {
              acknowledge = resolve;
            },
          );
        },
      ),
    } as unknown as ProductClient;
    const { result } = setup(client);
    act(() => {
      result.current.edit({ name: "One" });
      result.current.edit({ name: "Final" });
    });
    await waitFor(() => expect(saves).toHaveLength(1));
    expect(result.current.status).toBe("saving");
    expect(saves[0]).toMatchObject({ version: 1, name: "Final" });
    await act(async () =>
      acknowledge({ id: "p1", version: 2, status: "draft" }),
    );
    await waitFor(() => expect(result.current.status).toBe("saved"));
    expect(client.saveProduct).toHaveBeenCalledTimes(1);
  });

  it("serializes edits made during an in-flight save using the acknowledged version", async () => {
    const requests: Array<{
      version: number;
      name?: string | null;
      resolve: (value: {
        id: string;
        version: number;
        status: "draft";
      }) => void;
    }> = [];
    const saveProduct = vi.fn(
      (_id: string, payload: { version: number; name?: string | null }) =>
        new Promise<{ id: string; version: number; status: "draft" }>(
          (resolve) => requests.push({ ...payload, resolve }),
        ),
    );
    const { result } = setup({ saveProduct } as unknown as ProductClient, 5);
    act(() => result.current.edit({ name: "First" }));
    await waitFor(() => expect(requests).toHaveLength(1));
    act(() => result.current.edit({ name: "Second" }));
    await act(async () =>
      requests[0].resolve({ id: "p1", version: 2, status: "draft" }),
    );
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[1]).toMatchObject({ version: 2, name: "Second" });
    await act(async () =>
      requests[1].resolve({ id: "p1", version: 3, status: "draft" }),
    );
    await waitFor(() => expect(result.current.status).toBe("saved"));
  });

  it("retains failed edits and retries the latest values when connection returns", async () => {
    const save = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValue({ id: "p1", version: 2, status: "draft" });
    const client = { saveProduct: save } as unknown as ProductClient;
    const { result } = setup(client);
    act(() => result.current.edit({ name: "Retained" }));
    await waitFor(() => expect(result.current.status).toBe("not-saved"));
    expect(result.current.values.name).toBe("Retained");
    await act(async () => {
      fireEvent(window, new Event("online"));
    });
    await waitFor(() => expect(result.current.status).toBe("saved"));
    expect(save).toHaveBeenLastCalledWith(
      "p1",
      expect.objectContaining({ name: "Retained" }),
    );
  });

  it("pauses after a version conflict without discarding local edits", async () => {
    const conflict = Object.assign(new Error("conflict"), { status: 409 });
    const save = vi.fn().mockRejectedValue(conflict);
    const { result } = setup({ saveProduct: save } as unknown as ProductClient);
    act(() => result.current.edit({ name: "Mine" }));
    await waitFor(() => expect(result.current.status).toBe("conflict"));
    expect(result.current.values.name).toBe("Mine");
    expect(save).toHaveBeenCalledTimes(1);
    await act(async () => result.current.retry());
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("uses an acknowledged attachment version for the next autosave", async () => {
    const save = vi
      .fn()
      .mockResolvedValueOnce({ id: "p1", version: 2, status: "draft" })
      .mockResolvedValueOnce({ id: "p1", version: 4, status: "draft" });
    const { result } = setup({ saveProduct: save } as unknown as ProductClient);

    act(() => result.current.edit({ name: "Before attachment" }));
    await waitFor(() => expect(result.current.status).toBe("saved"));
    act(() => result.current.adoptVersion(3));
    expect(result.current.version).toBe(3);
    act(() => result.current.edit({ pitch: "After attachment" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save).toHaveBeenLastCalledWith(
      "p1",
      expect.objectContaining({ version: 3, pitch: "After attachment" }),
    );
  });
});
