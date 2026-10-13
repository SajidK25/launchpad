// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NotificationBell } from "./NotificationBell";
import { useCurrentSession } from "../identity/useIdentity";
import { useNotificationInbox } from "./useNotifications";

vi.mock("../identity/useIdentity", () => ({ useCurrentSession: vi.fn() }));
vi.mock("./useNotifications", () => ({ useNotificationInbox: vi.fn() }));
vi.mock("../identity/Screens", () => ({ navigate: vi.fn() }));

const sessionHook = vi.mocked(useCurrentSession);
const inboxHook = vi.mocked(useNotificationInbox);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("notification bell", () => {
  it("opens and closes the inbox without marking any item read", () => {
    const markRead = vi.fn();
    inboxHook.mockReturnValue({
      inbox: { data: { items: [notice], unreadCount: 2, nextCursor: null } },
      markRead,
      isMarkingRead: false,
      markError: null,
    } as never);
    sessionHook.mockReturnValue({ data: memberSession } as never);
    render(
      <NotificationBell identityClient={{} as never} client={{} as never} />,
    );

    const button = screen.getByRole("button", {
      name: "Notifications, 2 unread",
    });
    fireEvent.click(button);
    expect(
      screen.getByRole("region", { name: "Notifications" }),
    ).not.toBeNull();
    expect(markRead).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Notifications" })).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it("marks only the selected notification and opens the founder product workspace", async () => {
    const markRead = vi.fn().mockResolvedValue(undefined);
    inboxHook.mockReturnValue({
      inbox: {
        data: {
          items: [
            notice,
            {
              ...notice,
              id: "notice-2",
              kind: "review_changes_requested" as const,
            },
          ],
          unreadCount: 2,
          nextCursor: null,
        },
      },
      markRead,
      isMarkingRead: false,
      markError: null,
    } as never);
    sessionHook.mockReturnValue({ data: memberSession } as never);
    const { navigate } = await import("../identity/Screens");
    render(
      <NotificationBell identityClient={{} as never} client={{} as never} />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Notifications, 2 unread" }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Approval received/ }));

    await waitFor(() => expect(markRead).toHaveBeenCalledWith("notice-1"));
    expect(markRead).toHaveBeenCalledOnce();
    expect(navigate).toHaveBeenCalledWith("/products/product-1", {
      focusProductMain: true,
    });
  });

  it("does not show private notices outside an active founder session", () => {
    sessionHook.mockReturnValue({
      data: { ...memberSession, suspended: true },
    } as never);
    inboxHook.mockReturnValue({ inbox: { data: undefined } } as never);
    render(
      <NotificationBell identityClient={{} as never} client={{} as never} />,
    );
    expect(screen.queryByRole("button", { name: /Notifications/ })).toBeNull();
  });

  it("shows an empty inbox and a zero unread count", () => {
    sessionHook.mockReturnValue({ data: memberSession } as never);
    inboxHook.mockReturnValue({
      inbox: { data: { items: [], unreadCount: 0, nextCursor: null } },
      markRead: vi.fn(),
      isMarkingRead: false,
      markError: null,
    } as never);
    render(
      <NotificationBell identityClient={{} as never} client={{} as never} />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Notifications, 0 unread" }),
    );

    expect(screen.getByText("No review updates yet.")).not.toBeNull();
  });

  it("announces an updated unread count after a live refresh", async () => {
    sessionHook.mockReturnValue({ data: memberSession } as never);
    inboxHook.mockReturnValue({
      inbox: { data: { items: [notice], unreadCount: 1, nextCursor: null } },
      markRead: vi.fn(),
      isMarkingRead: false,
      markError: null,
    } as never);
    const view = render(
      <NotificationBell identityClient={{} as never} client={{} as never} />,
    );
    expect(
      screen.getByRole("button", { name: "Notifications, 1 unread" }),
    ).not.toBeNull();

    inboxHook.mockReturnValue({
      inbox: {
        data: {
          items: [{ ...notice, id: "notice-2" }],
          unreadCount: 4,
          nextCursor: null,
        },
      },
      markRead: vi.fn(),
      isMarkingRead: false,
      markError: null,
    } as never);
    view.rerender(
      <NotificationBell identityClient={{} as never} client={{} as never} />,
    );

    expect(
      screen.getByRole("button", { name: "Notifications, 4 unread" }),
    ).not.toBeNull();
    await waitFor(() =>
      expect(screen.getByText("You have 4 unread review updates.")).not.toBeNull(),
    );
  });
});

const memberSession = {
  account_id: "founder-1",
  role: "member",
  suspended: false,
  verified: true,
  csrf_token: "csrf",
};

const notice = {
  id: "notice-1",
  productId: "product-1",
  kind: "review_approved" as const,
  createdAt: "2026-10-02T00:00:00Z",
  readAt: null,
};
