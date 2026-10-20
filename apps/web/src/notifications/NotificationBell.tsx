import { useEffect, useRef, useState } from "react";
import { navigate } from "../routing";
import type { IdentityClient } from "../identity/client";
import { useCurrentSession } from "../identity/useIdentity";
import { createNotificationClient } from "./client";
import { useNotificationInbox } from "./useNotifications";

const outcomeCopy = {
  review_approved: "Approval received",
  review_rejected: "Product rejected",
  review_changes_requested: "Changes requested",
} as const;

export function NotificationBell({
  identityClient,
  client,
}: {
  identityClient: IdentityClient;
  client?: ReturnType<typeof createNotificationClient>;
}) {
  const [notificationClient] = useState(
    () => client ?? createNotificationClient(undefined, identityClient),
  );
  const session = useCurrentSession(identityClient);
  const founderSession =
    session.data?.role === "member" &&
    session.data.verified &&
    !session.data.suspended
      ? session.data
      : null;
  const notifications = useNotificationInbox(
    notificationClient,
    founderSession,
  );
  const [open, setOpen] = useState(false);
  const [countAnnouncement, setCountAnnouncement] = useState("");
  const buttonRef = useRef<HTMLButtonElement>(null);
  const previousUnreadCount = useRef<number | null>(null);
  const items = notifications.inbox.data?.items ?? [];
  const unreadCount = notifications.inbox.data?.unreadCount ?? 0;
  const hasFounderSession = founderSession !== null;

  useEffect(() => {
    if (!hasFounderSession) {
      previousUnreadCount.current = null;
      setCountAnnouncement("");
      return;
    }
    if (previousUnreadCount.current === null) {
      previousUnreadCount.current = unreadCount;
      return;
    }
    if (previousUnreadCount.current !== unreadCount) {
      setCountAnnouncement(
        unreadCount === 1
          ? "You have 1 unread review update."
          : `You have ${unreadCount} unread review updates.`,
      );
      previousUnreadCount.current = unreadCount;
    }
  }, [hasFounderSession, unreadCount]);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  if (!founderSession) return null;

  async function openNotification(id: string, productId: string) {
    try {
      await notifications.markRead(id);
      setOpen(false);
      navigate(`/products/${encodeURIComponent(productId)}`, {
        focusProductMain: true,
      });
    } catch {
      // Keep the item visible and unread when its read command fails.
    }
  }

  return (
    <div className="notification-bell">
      <button
        aria-expanded={open}
        aria-controls="notification-inbox"
        aria-label={`Notifications, ${unreadCount} unread`}
        className="notification-bell-trigger"
        onClick={() => setOpen((value) => !value)}
        ref={buttonRef}
        type="button"
      >
        <span aria-hidden="true">♢</span>
        <span>Notifications</span>
        <span aria-hidden="true" className="notification-unread-count">
          {unreadCount > 99 ? "99+" : unreadCount}
        </span>
      </button>
      <span aria-atomic="true" aria-live="polite" className="sr-only">
        {countAnnouncement}
      </span>
      {open ? (
        <section
          aria-label="Notifications"
          className="notification-inbox"
          id="notification-inbox"
          role="region"
        >
          <h2>Review updates</h2>
          {notifications.inbox.isPending ? (
            <p role="status">Loading notifications…</p>
          ) : null}
          {notifications.inbox.isError ? (
            <p role="alert">Notifications are unavailable. Try again later.</p>
          ) : null}
          {notifications.markError ? (
            <p role="alert">
              This update could not be opened. It remains unread.
            </p>
          ) : null}
          {items.length === 0 && !notifications.inbox.isPending ? (
            <p>No review updates yet.</p>
          ) : null}
          <ul aria-label="Review outcome notifications">
            {items.map((item) => (
              <li key={item.id}>
                <button
                  aria-label={`${outcomeCopy[item.kind]}${item.readAt ? "" : ", unread"}`}
                  className={`notification-item${item.readAt ? " notification-item--read" : " notification-item--unread"}`}
                  disabled={notifications.isMarkingRead}
                  onClick={() => void openNotification(item.id, item.productId)}
                  type="button"
                >
                  <span>{outcomeCopy[item.kind]}</span>
                  <span className="notification-item-state">
                    {item.readAt ? "Read" : "Unread"}
                  </span>
                  <time dateTime={item.createdAt}>
                    {new Date(item.createdAt).toLocaleDateString()}
                  </time>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
