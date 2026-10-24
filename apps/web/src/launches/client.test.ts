import { describe, expect, it, vi } from "vitest";
import { createLaunchClient, LaunchRequestTimeoutError } from "./client";

describe("launch client", () => {
  it("fetches the ranked daily feed anonymously", async () => {
    const page = {
      todayDate: "2026-11-01",
      selectedDate: "2026-10-31",
      hasSnapshot: true,
      items: [],
      nextCursor: null,
    };
    const fetcher = vi.fn(async (_input, init) => {
      const request = JSON.parse(String(init?.body)) as {
        query: string;
        variables: unknown;
      };
      expect(request.query).toContain("query DailyProductRanking");
      expect(request.variables).toEqual({ date: "2026-10-31", first: 20 });
      return Response.json({ data: { dailyProductRanking: page } });
    });
    const identity = {
      ensureSession: vi.fn(),
      getCsrfToken: vi.fn(() => null),
    };
    const client = createLaunchClient(fetcher, identity);

    await expect(
      client.fetchDailyProductRanking({ date: "2026-10-31", first: 20 }),
    ).resolves.toEqual(page);
    expect(identity.ensureSession).not.toHaveBeenCalled();
  });

  it("fetches today anonymously without initializing a session", async () => {
    const fetcher = vi.fn(async () =>
      Response.json({
        data: {
          publicLaunches: {
            todayDate: "2026-11-01",
            selectedDate: "2026-11-01",
            items: [],
            nextCursor: null,
          },
        },
      }),
    );
    const identity = {
      ensureSession: vi.fn(),
      getCsrfToken: vi.fn(() => null),
    };
    const client = createLaunchClient(fetcher, identity);

    await client.fetchPublicLaunches();

    expect(identity.ensureSession).not.toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/graphql",
      expect.objectContaining({
        body: expect.not.stringContaining('"date"'),
      }),
    );
  });

  it("sends an archive date and cursor using generated operation variables", async () => {
    const fetcher = vi.fn(async (_input, init) => {
      const request = JSON.parse(String(init?.body)) as {
        variables: unknown;
      };
      expect(request.variables).toEqual({
        date: "2026-10-31",
        first: 20,
        after: "cursor-next",
      });
      return Response.json({
        data: {
          publicLaunches: {
            todayDate: "2026-11-01",
            selectedDate: "2026-10-31",
            items: [],
            nextCursor: null,
          },
        },
      });
    });
    const client = createLaunchClient(fetcher, {
      ensureSession: vi.fn(),
      getCsrfToken: vi.fn(() => null),
    });

    const page = await client.fetchPublicLaunches({
      date: "2026-10-31",
      first: 20,
      after: "cursor-next",
    });

    expect(page.selectedDate).toBe("2026-10-31");
  });

  it("surfaces GraphQL errors instead of synthesizing an empty page", async () => {
    const fetcher = vi.fn(async () =>
      Response.json({ errors: [{ message: "Launch list unavailable." }] }),
    );
    const client = createLaunchClient(fetcher, {
      ensureSession: vi.fn(),
      getCsrfToken: vi.fn(() => null),
    });

    await expect(client.fetchPublicLaunches()).rejects.toMatchObject({
      name: "LaunchRequestError",
      status: 200,
    });
  });

  it("fetches the public catalog anonymously with search, topics, and cursor", async () => {
    const catalogPage = {
      items: [
        {
          id: "product-1",
          name: "Launchpad",
          pitch: "Build faster",
          logoUrl: null,
          topics: ["Tools"],
        },
      ],
      nextCursor: "catalog-cursor-2",
    };
    const fetcher = vi.fn(async (_input, init) => {
      const request = JSON.parse(String(init?.body)) as {
        query: string;
        variables: unknown;
      };
      expect(request.query).toContain("query PublicProductCatalog");
      expect(request.variables).toEqual({
        search: "Launch",
        topicIds: ["topic-1", "topic-2"],
        first: 20,
        after: "catalog-cursor-1",
      });
      return Response.json({ data: { publicProductCatalog: catalogPage } });
    });
    const identity = {
      ensureSession: vi.fn(),
      getCsrfToken: vi.fn(() => null),
    };
    const client = createLaunchClient(fetcher, identity);
    const controller = new AbortController();

    await expect(
      client.fetchPublicCatalog(
        {
          search: "Launch",
          topicIds: ["topic-1", "topic-2"],
          first: 20,
          after: "catalog-cursor-1",
        },
        controller.signal,
      ),
    ).resolves.toEqual(catalogPage);

    expect(identity.ensureSession).not.toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/graphql",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("hydrates selected topic labels anonymously", async () => {
    const options = {
      choices: [{ id: "topic-2", displayName: "Productivity" }],
      selected: [{ id: "topic-1", displayName: "Developer tools" }],
    };
    const fetcher = vi.fn(async (_input, init) => {
      const request = JSON.parse(String(init?.body)) as {
        query: string;
        variables: unknown;
      };
      expect(request.query).toContain("query PublicCatalogTopics");
      expect(request.variables).toEqual({
        query: "dev",
        selectedIds: ["topic-1", "topic-3"],
        first: 20,
      });
      return Response.json({ data: { publicCatalogTopics: options } });
    });
    const identity = {
      ensureSession: vi.fn(),
      getCsrfToken: vi.fn(() => null),
    };
    const client = createLaunchClient(fetcher, identity);
    const controller = new AbortController();

    await expect(
      client.fetchPublicCatalogTopics(
        { query: "dev", selectedIds: ["topic-1", "topic-3"], first: 20 },
        controller.signal,
      ),
    ).resolves.toEqual(options);
    expect(identity.ensureSession).not.toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/graphql",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("forwards catalog read failures instead of returning empty results", async () => {
    const fetcher = vi.fn(async () =>
      Response.json({
        errors: [{ message: "request could not be completed" }],
      }),
    );
    const client = createLaunchClient(fetcher, {
      ensureSession: vi.fn(),
      getCsrfToken: vi.fn(() => null),
    });

    await expect(client.fetchPublicCatalog()).rejects.toMatchObject({
      name: "LaunchRequestError",
      status: 200,
    });
  });

  it("aborts an in-flight catalog request when its query signal is cancelled", async () => {
    let requestSignal: AbortSignal | undefined;
    const fetcher = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          requestSignal = init?.signal ?? undefined;
          requestSignal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );
    const client = createLaunchClient(fetcher, {
      ensureSession: vi.fn(),
      getCsrfToken: vi.fn(() => null),
    });
    const controller = new AbortController();

    const request = client.fetchPublicCatalog({}, controller.signal);
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(requestSignal?.aborted).toBe(true);
  });

  it("times out a stalled public launch request and aborts its fetch", async () => {
    vi.useFakeTimers();
    let requestSignal: AbortSignal | undefined;
    const fetcher = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          requestSignal = init?.signal ?? undefined;
          requestSignal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );
    const client = createLaunchClient(fetcher, {
      ensureSession: vi.fn(),
      getCsrfToken: vi.fn(() => null),
    });

    try {
      const request = client.fetchPublicLaunches();
      const requestRejection = expect(request).rejects.toBeInstanceOf(
        LaunchRequestTimeoutError,
      );
      await vi.advanceTimersByTimeAsync(15_000);
      await requestRejection;
      expect(requestSignal?.aborted).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("serializes a UTC calendar date without converting through local time", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            booking_id: "booking-1",
            product_id: "product-1",
            state: "scheduled",
            launch_date: "2026-11-01",
            launch_at: "2026-11-01T00:00:00Z",
            product_status: "scheduled",
            product_version: 8,
          }),
          { status: 200 },
        ),
    );
    const identity = {
      ensureSession: vi.fn(async () => ({
        account_id: "founder-1",
        csrf_token: "csrf-token",
        role: "member" as const,
        suspended: false,
        verified: true,
      })),
      getCsrfToken: vi.fn(() => "csrf-token"),
    };
    const client = createLaunchClient(fetcher, identity);

    const result = await client.createBooking(
      "product-1",
      { launch_date: "2026-11-01", expected_version: 7 },
      "booking-key-1",
    );

    expect(result.launch_date).toBe("2026-11-01");
    expect(result.launch_at).toBe("2026-11-01T00:00:00Z");
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/me/products/product-1/launch-booking",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({
          launch_date: "2026-11-01",
          expected_version: 7,
        }),
        headers: expect.objectContaining({
          "Idempotency-Key": "booking-key-1",
          "X-CSRF-Token": "csrf-token",
        }),
      }),
    );
  });

  it("sends expected versions and idempotency keys for reschedule and cancellation", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            booking_id: "booking-1",
            product_id: "product-1",
            state: "scheduled",
            launch_date: "2026-11-02",
            launch_at: "2026-11-02T00:00:00Z",
            product_status: "scheduled",
            product_version: 9,
          }),
          { status: 200 },
        ),
    );
    const client = createLaunchClient(fetcher, {
      ensureSession: vi.fn(async () => ({
        account_id: "founder-1",
        csrf_token: "csrf-token",
        role: "member" as const,
        suspended: false,
        verified: true,
      })),
      getCsrfToken: vi.fn(() => null),
    });

    await client.rescheduleBooking(
      "product-1",
      { launch_date: "2026-11-02", expected_version: 8 },
      "reschedule-key",
    );
    await client.cancelBooking("product-1", 9, "cancel-key");

    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "/api/v1/me/products/product-1/launch-booking",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          launch_date: "2026-11-02",
          expected_version: 8,
        }),
        headers: expect.objectContaining({
          "Idempotency-Key": "reschedule-key",
        }),
      }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "/api/v1/me/products/product-1/launch-booking?expected_version=9",
      expect.objectContaining({
        method: "DELETE",
        headers: expect.objectContaining({ "Idempotency-Key": "cancel-key" }),
      }),
    );
  });

  it("reads and writes each of the six launch notice preferences", async () => {
    const preferences = {
      reminder_email: false,
      reminder_in_site: true,
      live_email: true,
      live_in_site: false,
      failure_email: false,
      failure_in_site: true,
    };
    const graphqlPreferences = {
      reminderEmail: false,
      reminderInSite: true,
      liveEmail: true,
      liveInSite: false,
      failureEmail: false,
      failureInSite: true,
    };
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: { viewerLaunchNotificationPreferences: graphqlPreferences },
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(preferences), { status: 200 }),
      );
    const client = createLaunchClient(fetcher, {
      ensureSession: vi.fn(async () => ({
        account_id: "founder-1",
        csrf_token: "csrf-token",
        role: "member" as const,
        suspended: false,
        verified: true,
      })),
      getCsrfToken: vi.fn(() => "csrf-token"),
    });

    await expect(client.fetchLaunchPreferences()).resolves.toEqual({
      reminderEmail: false,
      reminderInSite: true,
      liveEmail: true,
      liveInSite: false,
      failureEmail: false,
      failureInSite: true,
    });
    await expect(client.updateLaunchPreferences(preferences)).resolves.toEqual(
      preferences,
    );

    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "/api/v1/graphql",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining("viewerLaunchNotificationPreferences"),
      }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "/api/v1/me/launch-notification-preferences",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify(preferences),
      }),
    );
  });
});
