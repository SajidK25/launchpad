import { describe, expect, it, vi } from "vitest";
import { createNotificationClient } from "./client";

describe("notification client", () => {
  it("reads inbox paging and unread count from generated GraphQL fields", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      Response.json({
        data: {
          viewerNotificationInbox: {
            items: [
              {
                id: "notice-1",
                productId: "product-1",
                kind: "REVIEW_APPROVED",
                createdAt: "2026-10-01T00:00:00Z",
                readAt: null,
              },
            ],
            unreadCount: 1,
            nextCursor: "cursor-2",
          },
        },
      }),
    );
    const client = createNotificationClient(fetcher, identity);

    const page = await client.fetchInbox({ first: 1, after: "cursor-1" });

    expect(page.unreadCount).toBe(1);
    expect(page.items[0]?.kind).toBe("review_approved");
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      query: expect.stringContaining("viewerNotificationInbox"),
      variables: { first: 1, after: "cursor-1" },
    });
  });

  it("marks only the selected item using the session CSRF token", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      Response.json({
        id: "notice-2",
        product_id: "product-2",
        kind: "review_rejected",
        created_at: "2026-10-02T00:00:00Z",
        read_at: "2026-10-03T00:00:00Z",
      }),
    );
    const client = createNotificationClient(fetcher, identity);

    const result = await client.markRead("notice-2");

    expect(result.id).toBe("notice-2");
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/me/notifications/notice-2/read",
      expect.objectContaining({
        method: "PUT",
        credentials: "include",
        headers: {
          "X-CSRF-Token": "csrf-token",
        },
      }),
    );
  });
});

const identity = {
  ensureSession: vi.fn().mockResolvedValue({}),
  getCsrfToken: () => "csrf-token",
};
