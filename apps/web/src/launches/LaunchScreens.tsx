import {
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import type { ViewerProductsQuery } from "@launchpad/contracts/src/graphql.generated";
import { createProductClient } from "../products/client";
import { useViewerProducts } from "../products/useProducts";
import type { IdentityClient } from "../identity/client";
import { navigate } from "../identity/Screens";
import { useCurrentSession, useLogout } from "../identity/useIdentity";
import { createNotificationClient } from "../notifications/client";
import { NotificationBell } from "../notifications/NotificationBell";
import {
  createLaunchClient,
  LaunchRequestError,
  type LaunchBookingPage,
  type LaunchClient,
} from "./client";
import {
  useBookLaunch,
  useCancelLaunch,
  useLaunchBookings,
  useLaunchLiveInvalidation,
  useLaunchPreferences,
  useRescheduleLaunch,
  useUpdateLaunchPreferences,
} from "./useLaunches";

const preferenceFields = [
  ["reminderEmail", "Email reminders"],
  ["reminderInSite", "In-site reminders"],
  ["liveEmail", "Email when a launch goes live"],
  ["liveInSite", "In-site launch alerts"],
  ["failureEmail", "Email when a launch cannot publish"],
  ["failureInSite", "In-site failure alerts"],
] as const;

type PreferenceName = (typeof preferenceFields)[number][0];
type LaunchProduct = ViewerProductsQuery["viewerProducts"]["items"][number];
type LaunchBooking = LaunchBookingPage["items"][number];

function tomorrowUtc(): string {
  const tomorrow = new Date();
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
  return tomorrow.toISOString().slice(0, 10);
}

function maxLaunchDateUtc(): string {
  const latest = new Date();
  latest.setUTCDate(latest.getUTCDate() + 90);
  return latest.toISOString().slice(0, 10);
}

function requestErrorMessage(error: unknown): string {
  if (error instanceof LaunchRequestError && error.status === 409)
    return "That launch slot is no longer available or the product changed. Refresh the dashboard and choose another date.";
  return "We could not save this launch change. Your current booking is unchanged. Please try again.";
}

function launchStateCopy(state: string, failureReason: string | null): string {
  if (state === "scheduled") return "Scheduled";
  if (state === "launched") return "Published";
  if (state === "missed_day" || failureReason === "missed_day")
    return "Missed launch day — choose a new date";
  if (state === "suspension_blocked" || failureReason === "suspension_blocked")
    return "Launch blocked while the account is suspended";
  if (state === "cancelled") return "Cancelled";
  if (state === "replaced") return "Rescheduled";
  if (state === "returned_for_changes") return "Returned for changes";
  return "Launch update";
}

export function LaunchRoutes({
  identityClient,
}: {
  identityClient: IdentityClient;
}) {
  const launchClient = useMemo(
    () => createLaunchClient(undefined, identityClient),
    [identityClient],
  );
  const productClient = useMemo(
    () => createProductClient(undefined, identityClient),
    [identityClient],
  );
  const notificationClient = useMemo(
    () => createNotificationClient(undefined, identityClient),
    [identityClient],
  );
  const session = useCurrentSession(identityClient);
  const founderSession = session.data?.role === "member" ? session.data : null;
  if (session.isPending)
    return (
      <LaunchStatus title="Launch calendar" message="Checking your account…" />
    );
  if (session.isError || !founderSession)
    return (
      <LaunchStatus
        title="Founder launch calendar"
        message="Sign in with a founder account to manage launch dates."
        action={
          <a className="launch-button" href="/signin">
            Sign in
          </a>
        }
      />
    );

  return (
    <FounderLaunchDashboard
      identityClient={identityClient}
      launchClient={launchClient}
      notificationClient={notificationClient}
      productClient={productClient}
      session={founderSession}
    />
  );
}

function FounderLaunchDashboard({
  identityClient,
  launchClient,
  notificationClient,
  productClient,
  session,
}: {
  identityClient: IdentityClient;
  launchClient: LaunchClient;
  notificationClient: ReturnType<typeof createNotificationClient>;
  productClient: ReturnType<typeof createProductClient>;
  session: Awaited<ReturnType<IdentityClient["currentSession"]>>;
}) {
  const accountId = session.account_id;
  const bookings = useLaunchBookings(launchClient, session);
  const preferences = useLaunchPreferences(launchClient, session);
  const products = useViewerProducts(productClient);
  const savePreferences = useUpdateLaunchPreferences(launchClient, accountId);
  const logout = useLogout(identityClient);
  useLaunchLiveInvalidation(notificationClient, session);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function updatePreference(name: PreferenceName, checked: boolean) {
    if (!preferences.data) return;
    setNotice("");
    setError("");
    const values = preferences.data;
    try {
      await savePreferences.mutateAsync({
        reminder_email:
          name === "reminderEmail" ? checked : values.reminderEmail,
        reminder_in_site:
          name === "reminderInSite" ? checked : values.reminderInSite,
        live_email: name === "liveEmail" ? checked : values.liveEmail,
        live_in_site: name === "liveInSite" ? checked : values.liveInSite,
        failure_email: name === "failureEmail" ? checked : values.failureEmail,
        failure_in_site:
          name === "failureInSite" ? checked : values.failureInSite,
      });
      setNotice("Notification preference saved.");
    } catch {
      setError(
        "We could not save this preference. Your saved choices remain unchanged.",
      );
    }
  }

  async function signOut() {
    try {
      await logout.mutateAsync();
      navigate("/signin");
    } catch {
      setError("We could not sign you out. Please try again.");
    }
  }

  const availableProducts =
    products.data?.items.filter((product) =>
      ["approved", "scheduled", "launched"].includes(product.status),
    ) ?? [];
  const bookingByProduct = new Map<string, LaunchBooking>();
  for (const booking of bookings.data?.items ?? []) {
    if (!bookingByProduct.has(booking.productId))
      bookingByProduct.set(booking.productId, booking);
  }

  return (
    <main className="launch-shell" id="launch-main" tabIndex={-1}>
      <div className="launch-workspace">
        <header className="launch-topbar">
          <a className="launch-brand" href="/products">
            LAUNCHPAD <span>FOUNDER WORKSPACE</span>
          </a>
          <nav aria-label="Founder workspace navigation" className="launch-nav">
            <NotificationBell identityClient={identityClient} />
            <a href="/products">Your products</a>
            <a href="/profile">Profile</a>
            <button
              disabled={logout.isPending}
              onClick={() => void signOut()}
              type="button"
            >
              {logout.isPending ? "Signing out…" : "Sign out"}
            </button>
          </nav>
        </header>

        <section aria-labelledby="launch-title" className="launch-hero">
          <p className="launch-kicker">ONE RELEASE AT A TIME</p>
          <h1 id="launch-title">Your launch calendar</h1>
          <p>
            Choose a UTC launch day for an approved product. Launches publish at
            00:00 UTC on the booked date.
          </p>
          <div aria-label="Launch scheduling rules" className="launch-rule">
            <span>UTC CUTOFF</span>
            <strong>00:00</strong>
            <span>DAILY CAPACITY</span>
            <strong>ONE PER FOUNDER</strong>
          </div>
        </section>

        <section aria-labelledby="products-heading" className="launch-panel">
          <div className="launch-section-heading">
            <div>
              <p className="launch-kicker">SCHEDULE & TRACK</p>
              <h2 id="products-heading">Products</h2>
            </div>
            <a className="launch-text-link" href="/products">
              Manage product details ↗
            </a>
          </div>
          {products.isPending || bookings.isPending ? (
            <p role="status">Loading your launch calendar…</p>
          ) : null}
          {products.isError || bookings.isError ? (
            <p className="launch-error" role="alert">
              Your launch calendar could not be loaded. Refresh and try again.
            </p>
          ) : null}
          {!products.isPending &&
          !products.isError &&
          !bookings.isPending &&
          !bookings.isError &&
          availableProducts.length === 0 ? (
            <div className="launch-empty">
              <span aria-hidden="true" className="launch-empty-mark">
                01
              </span>
              <div>
                <h3>No approved products yet</h3>
                <p>
                  Once a product is approved, you can reserve a launch date
                  here.
                </p>
              </div>
              <a className="launch-button launch-button-dark" href="/products">
                View your products
              </a>
            </div>
          ) : null}
          <div className="launch-product-list">
            {availableProducts.map((product) => (
              <LaunchProductCard
                accountId={accountId}
                booking={bookingByProduct.get(product.id)}
                client={launchClient}
                key={product.id}
                product={product}
                sessionVerified={session.verified}
                suspended={session.suspended}
              />
            ))}
          </div>
          {notice ? (
            <p className="launch-success" role="status">
              {notice}
            </p>
          ) : null}
          {error ? (
            <p className="launch-error" role="alert">
              {error}
            </p>
          ) : null}
        </section>

        <section
          aria-labelledby="preferences-heading"
          className="launch-panel launch-preferences"
        >
          <div className="launch-section-heading">
            <div>
              <p className="launch-kicker">STAY IN THE LOOP</p>
              <h2 id="preferences-heading">Launch notifications</h2>
            </div>
            <span className="launch-pref-count">6 CHANNELS</span>
          </div>
          <p className="launch-panel-intro">
            Choose how Launchpad keeps you informed about reminders, live
            launches, and publication failures.
          </p>
          {preferences.isPending ? (
            <p role="status">Loading notification preferences…</p>
          ) : null}
          {preferences.isError ? (
            <p className="launch-error" role="alert">
              Notification preferences could not be loaded.
            </p>
          ) : null}
          {preferences.data ? (
            <fieldset
              className="launch-preference-list"
              disabled={savePreferences.isPending}
            >
              <legend className="sr-only">
                Choose launch notification channels
              </legend>
              {preferenceFields.map(([name, label]) => (
                <label className="launch-preference" key={name}>
                  <span>{label}</span>
                  <input
                    checked={preferences.data[name]}
                    onChange={(event) =>
                      void updatePreference(name, event.target.checked)
                    }
                    type="checkbox"
                  />
                </label>
              ))}
            </fieldset>
          ) : null}
          {savePreferences.isPending ? (
            <p role="status">Saving preference…</p>
          ) : null}
          <p className="launch-timezone-note">
            All launch dates and automatic publishing times use UTC.
          </p>
        </section>
      </div>
    </main>
  );
}

function LaunchProductCard({
  accountId,
  booking,
  client,
  product,
  sessionVerified,
  suspended,
}: {
  accountId: string;
  booking: LaunchBooking | undefined;
  client: LaunchClient;
  product: LaunchProduct;
  sessionVerified: boolean;
  suspended: boolean;
}) {
  const book = useBookLaunch(client, product.id, accountId);
  const reschedule = useRescheduleLaunch(client, product.id, accountId);
  const cancel = useCancelLaunch(client, product.id, accountId);
  const [date, setDate] = useState(
    booking?.launchAt.slice(0, 10) ?? tomorrowUtc(),
  );
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const commandKey = useRef<{ signature: string; key: string } | null>(null);
  const busy = book.isPending || reschedule.isPending || cancel.isPending;
  const activeBooking = booking?.state === "scheduled" ? booking : undefined;
  const launched =
    product.status === "launched" || booking?.state === "launched";
  const canBook = product.status === "approved" && !activeBooking && !launched;
  const canChange =
    product.status === "scheduled" && activeBooking !== undefined;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("");
    setError("");
    const signature = `${canChange ? "reschedule" : "book"}:${date}:${product.version}`;
    const key = getCommandKey(commandKey, signature);
    try {
      const command = canChange ? reschedule : book;
      await command.mutateAsync({
        payload: { launch_date: date, expected_version: product.version },
        idempotencyKey: key,
      });
      commandKey.current = null;
      setNotice(
        canChange
          ? `Launch date updated to ${date} UTC.`
          : `Launch booked for ${date} UTC.`,
      );
    } catch (caught) {
      setError(requestErrorMessage(caught));
    }
  }

  async function cancelBooking() {
    setNotice("");
    setError("");
    const key = getCommandKey(commandKey, `cancel:${product.version}`);
    try {
      await cancel.mutateAsync({
        expectedVersion: product.version,
        idempotencyKey: key,
      });
      commandKey.current = null;
      setNotice(
        "Launch booking cancelled. The product is approved and private.",
      );
    } catch (caught) {
      setError(requestErrorMessage(caught));
    }
  }

  return (
    <article className="launch-product-card">
      <div className="launch-card-heading">
        <div>
          <p className="launch-product-status">
            {product.status.toUpperCase()}
          </p>
          <h3>{product.name?.trim() || "Untitled product"}</h3>
          <p>{product.pitch?.trim() || "No short description yet"}</p>
        </div>
        <span
          className={`launch-badge ${launched ? "launch-badge-live" : activeBooking ? "launch-badge-booked" : ""}`}
        >
          {launched
            ? "LIVE"
            : activeBooking
              ? "DATE RESERVED"
              : "READY TO SCHEDULE"}
        </span>
      </div>
      {activeBooking ? (
        <p className="launch-scheduled-date">
          Launch day <strong>{formatUtcDate(activeBooking.launchAt)}</strong>{" "}
          <span>00:00 UTC</span>
        </p>
      ) : null}
      {booking && !activeBooking ? (
        <p className="launch-history-state" role="status">
          {launchStateCopy(booking.state, booking.failureReason)}
          {booking.failureReason === "missed_day" ||
          booking.failureReason === "suspension_blocked"
            ? ". The product is approved and can be scheduled again."
            : "."}
        </p>
      ) : null}
      {launched ? (
        <p className="launch-history-state" role="status">
          This product is live.{" "}
          <a href={`/launches/${encodeURIComponent(product.id)}`}>
            View public launch page
          </a>
        </p>
      ) : null}
      {canBook || canChange ? (
        <form
          className="launch-booking-form"
          onSubmit={(event) => void submit(event)}
        >
          <label htmlFor={`launch-date-${product.id}`}>
            {canChange ? "Choose a new launch day" : "Choose a launch day"}
            <span>UTC calendar date</span>
          </label>
          <input
            id={`launch-date-${product.id}`}
            max={maxLaunchDateUtc()}
            min={tomorrowUtc()}
            onChange={(event) => setDate(event.target.value)}
            required
            type="date"
            value={date}
          />
          <button
            className="launch-button launch-button-yellow"
            disabled={busy || !sessionVerified || suspended}
            type="submit"
          >
            {busy
              ? "Saving…"
              : canChange
                ? "Reschedule launch"
                : "Reserve launch date"}
          </button>
          {canChange ? (
            <button
              className="launch-button launch-button-outline"
              disabled={busy}
              onClick={() => void cancelBooking()}
              type="button"
            >
              Cancel booking
            </button>
          ) : null}
        </form>
      ) : null}
      {!sessionVerified && !launched ? (
        <p className="launch-note">
          Verify your email before booking a launch date.
        </p>
      ) : null}
      {suspended && !launched ? (
        <p className="launch-note">
          Launch booking is unavailable while your account is suspended.
        </p>
      ) : null}
      {notice ? (
        <p className="launch-success" role="status">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="launch-error" role="alert">
          {error}
        </p>
      ) : null}
      <a
        className="launch-text-link"
        href={`/products/${encodeURIComponent(product.id)}`}
      >
        Edit product ↗
      </a>
    </article>
  );
}

function getCommandKey(
  reference: { current: { signature: string; key: string } | null },
  signature: string,
): string {
  if (reference.current?.signature === signature) return reference.current.key;
  const key = crypto.randomUUID();
  reference.current = { signature, key };
  return key;
}

function LaunchStatus({
  title,
  message,
  action,
}: {
  title: string;
  message: string;
  action?: ReactNode;
}) {
  return (
    <main className="launch-shell">
      <section className="launch-panel launch-gate">
        <p className="launch-kicker">FOUNDER WORKSPACE</p>
        <h1>{title}</h1>
        <p role="status">{message}</p>
        {action}
      </section>
    </main>
  );
}

function formatUtcDate(value: string): string {
  const date = new Date(value);
  return new Intl.DateTimeFormat("en", {
    dateStyle: "long",
    timeZone: "UTC",
  }).format(date);
}
