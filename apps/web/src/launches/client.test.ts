import { describe, expect, it, vi } from "vitest";
import { createLaunchClient } from "./client";

describe("launch client", () => {
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
