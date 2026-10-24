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
import { useCurrentSession } from "../identity/useIdentity";
import { navigate } from "../routing";
import { createNotificationClient } from "../notifications/client";
import { useRankingLive } from "../votes/useRankingLive";
import {
  createLaunchClient,
  type DailyRankingItem,
  LaunchRequestError,
  type LaunchBookingPage,
  type LaunchClient,
  type PublicProduct,
} from "./client";
import {
  useBookLaunch,
  useCancelLaunch,
  useLaunchBookings,
  useLaunchLiveInvalidation,
  useLaunchPreferences,
  usePublicProduct,
  useDailyProductRanking,
  useRescheduleLaunch,
  useUpdateLaunchPreferences,
} from "./useLaunches";
import { LaunchDiscovery } from "./LaunchDiscovery";

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
      launchClient={launchClient}
      notificationClient={notificationClient}
      productClient={productClient}
      session={founderSession}
    />
  );
}

export function PublicLaunchPage({
  identityClient,
  productId,
}: {
  identityClient: IdentityClient;
  productId: string;
}) {
  const client = useMemo(
    () => createLaunchClient(undefined, identityClient),
    [identityClient],
  );
  const publicProduct = usePublicProduct(client, productId);
  const launchDate = publicProduct.data?.launchedAt
    ? new Date(publicProduct.data.launchedAt).toISOString().slice(0, 10)
    : undefined;
  const ranking = useDailyProductRanking(
    client,
    launchDate,
    productId,
    1,
    Boolean(publicProduct.data),
  );
  const rankingPage = ranking.data?.pages[0];
  useRankingLive({
    date: launchDate,
    enabled:
      launchDate !== undefined &&
      rankingPage !== undefined &&
      rankingPage.selectedDate === rankingPage.todayDate,
  });

  if (publicProduct.isPending)
    return (
      <PublicLaunchStatus
        title="Loading launch"
        message="Opening the public product page…"
      />
    );
  const data = publicProduct.data;
  if (publicProduct.isError || !data)
    return (
      <PublicLaunchStatus
        title="Launch not found"
        message="This launch is private or unavailable."
      />
    );

  const rankingItem =
    ranking.data?.pages.flatMap((page) => page.items)[0] ?? null;
  return <PublicLaunchDetails product={data} ranking={rankingItem} />;
}

export function PublicLaunchArchive({
  date,
  identityClient,
}: {
  date: string;
  identityClient: IdentityClient;
}) {
  const client = useMemo(
    () => createLaunchClient(undefined, identityClient),
    [identityClient],
  );

  return (
    <LaunchDiscovery
      client={client}
      date={date}
      onDateChange={(nextDate) => navigate(`/launches/archive/${nextDate}`)}
    />
  );
}

function PublicLaunchDetails({
  product,
  ranking,
}: {
  product: NonNullable<PublicProduct>;
  ranking: DailyRankingItem | null;
}) {
  const launchedDate = new Intl.DateTimeFormat("en", {
    dateStyle: "long",
    timeZone: "UTC",
  }).format(new Date(product.launchedAt));

  return (
    <div className="launch-shell public-launch-shell public-launch-page">
      <div className="launch-workspace">
        <span className="public-launch-stamp">NOW LIVE ↗</span>
        <article aria-labelledby="public-launch-title">
          <section className="public-launch-hero">
            <div className="public-launch-copy">
              <p className="launch-kicker">
                LAUNCHED {launchedDate} · 00:00 UTC
              </p>
              <h1 id="public-launch-title">{product.name}</h1>
              <p className="public-launch-pitch">{product.pitch}</p>
              {ranking &&
              ranking.rank !== null &&
              ranking.activeVoteCount !== null ? (
                <p
                  aria-label="Daily product ranking"
                  className="public-launch-ranking"
                >
                  RANK #{ranking.rank} · {ranking.activeVoteCount}{" "}
                  {ranking.activeVoteCount === 1 ? "vote" : "votes"}
                </p>
              ) : null}
              <a
                aria-label={`Visit ${product.name} website (opens in a new tab)`}
                className="launch-button launch-button-yellow public-launch-website"
                href={product.websiteUrl}
                rel="noreferrer"
                target="_blank"
              >
                Visit website ↗
              </a>
            </div>
            {product.logo ? (
              <figure className="public-launch-logo-frame">
                <img alt={`${product.name} logo`} src={product.logo.url} />
              </figure>
            ) : null}
          </section>

          {product.topics.length > 0 ? (
            <section
              aria-label="Product topics"
              className="public-launch-topics"
            >
              {product.topics.map((topic) => (
                <span className="public-launch-topic" key={topic}>
                  {topic}
                </span>
              ))}
            </section>
          ) : null}

          <section
            aria-labelledby="about-product"
            className="public-launch-about"
          >
            <div>
              <p className="launch-kicker">THE PRODUCT</p>
              <h2 id="about-product">A closer look</h2>
            </div>
            <p className="public-launch-description">{product.description}</p>
          </section>

          {product.screenshots.length > 0 ? (
            <section
              aria-labelledby="product-gallery"
              className="public-launch-gallery-section"
            >
              <div className="launch-section-heading">
                <div>
                  <p className="launch-kicker">IN THE FRAME</p>
                  <h2 id="product-gallery">Product gallery</h2>
                </div>
                <span className="public-launch-count">
                  {String(product.screenshots.length).padStart(2, "0")} IMAGES
                </span>
              </div>
              <div className="public-launch-gallery">
                {product.screenshots.map((screenshot, index) => (
                  <figure className="public-launch-shot" key={screenshot.id}>
                    <img
                      alt={`${product.name} screenshot ${index + 1}`}
                      loading="lazy"
                      src={screenshot.url}
                    />
                    <figcaption>
                      {String(index + 1).padStart(2, "0")} /{" "}
                      {String(product.screenshots.length).padStart(2, "0")}
                    </figcaption>
                  </figure>
                ))}
              </div>
            </section>
          ) : null}
        </article>
      </div>
    </div>
  );
}

function PublicLaunchStatus({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <section className="launch-shell public-launch-shell">
      <div className="launch-workspace">
        <section
          aria-labelledby="public-launch-status-title"
          className="launch-panel public-launch-status"
        >
          <p className="launch-kicker">PUBLIC PRODUCT PAGE</p>
          <h1 id="public-launch-status-title">{title}</h1>
          <p role="status">{message}</p>
          <a className="launch-button launch-button-dark" href="/">
            Back to Launchpad
          </a>
        </section>
      </div>
    </section>
  );
}

function FounderLaunchDashboard({
  launchClient,
  notificationClient,
  productClient,
  session,
}: {
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
    <div className="launch-shell" id="launch-main">
      <div className="launch-workspace">
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
            <strong>TWO PER FOUNDER</strong>
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
    </div>
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
    <section className="launch-shell launch-gate">
      <div className="launch-panel">
        <p className="launch-kicker">FOUNDER WORKSPACE</p>
        <h1>{title}</h1>
        <p role="status">{message}</p>
        {action}
      </div>
    </section>
  );
}

function formatUtcDate(value: string): string {
  const date = new Date(value);
  return new Intl.DateTimeFormat("en", {
    dateStyle: "long",
    timeZone: "UTC",
  }).format(date);
}
