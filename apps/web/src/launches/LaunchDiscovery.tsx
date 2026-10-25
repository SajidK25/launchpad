import type { LaunchClient } from "./client";
import type { IdentityClient } from "../identity/client";
import { RankedLaunchCard } from "../votes/RankedLaunchCard";
import { useRankingLive } from "../votes/useRankingLive";
import { useDailyProductRanking } from "./useLaunches";

export function LaunchDiscovery({
  client,
  identityClient,
  date,
  onDateChange,
  headingLevel = "h2",
}: {
  client: LaunchClient;
  identityClient: IdentityClient;
  date?: string;
  onDateChange: (date: string) => void;
  headingLevel?: "h1" | "h2";
}) {
  const launches = useDailyProductRanking(client, date);
  const firstPage = launches.data?.pages[0];
  const todayDate = firstPage?.todayDate;
  const selectedDate = firstPage?.selectedDate ?? date;
  const items = launches.data?.pages.flatMap((page) => page.items) ?? [];
  const Heading = headingLevel;
  useRankingLive({
    date,
    enabled:
      todayDate !== undefined &&
      (date === undefined || selectedDate === todayDate),
  });

  return (
    <section aria-labelledby="launch-discovery-title" className="launch-panel">
      <header className="launch-section-heading launch-discovery-heading">
        <div>
          <p className="launch-kicker">PUBLIC RELEASES</p>
          <Heading id="launch-discovery-title">
            {selectedDate === todayDate
              ? "Today’s launches"
              : "Launches on this day"}
          </Heading>
          {selectedDate ? (
            <p className="launch-discovery-date-label">
              {formatUtcDate(selectedDate)}
            </p>
          ) : null}
        </div>
        {selectedDate && todayDate ? (
          <nav aria-label="Launch dates" className="launch-date-controls">
            <button
              className="launch-button launch-button-outline"
              onClick={() => onDateChange(shiftUtcDate(selectedDate, -1))}
              type="button"
            >
              ← Previous day
            </button>
            <label className="launch-date-picker">
              <span>Choose a UTC date</span>
              <input
                aria-label="Choose a UTC date"
                max={todayDate}
                onChange={(event) => {
                  if (event.currentTarget.value)
                    onDateChange(event.currentTarget.value);
                }}
                type="date"
                value={selectedDate}
              />
            </label>
            <button
              className="launch-button launch-button-outline"
              disabled={selectedDate >= todayDate}
              onClick={() => onDateChange(shiftUtcDate(selectedDate, 1))}
              type="button"
            >
              Next day →
            </button>
          </nav>
        ) : null}
      </header>

      {launches.isPending ? (
        <p className="launch-discovery-state" role="status">
          Loading launches…
        </p>
      ) : launches.isError ? (
        <div className="launch-discovery-state launch-discovery-error">
          <p role="alert">Launches could not be loaded. Try again.</p>
          <button
            className="launch-button launch-button-yellow"
            disabled={launches.isFetching}
            onClick={() => void launches.refetch()}
            type="button"
          >
            {launches.isFetching ? "Retrying…" : "Retry"}
          </button>
        </div>
      ) : items.length === 0 ? (
        <>
          <p className="sr-only" role="status">
            No launches for{" "}
            {selectedDate ? formatUtcDate(selectedDate) : "today"}.
          </p>
          <div className="launch-empty launch-discovery-empty">
            <span aria-hidden="true" className="launch-empty-mark">
              0
            </span>
            <div>
              <h3>No launches on this day</h3>
              <p>Choose another date to explore launches.</p>
            </div>
          </div>
        </>
      ) : (
        <>
          <p className="sr-only" role="status">
            Showing {items.length} {items.length === 1 ? "launch" : "launches"}{" "}
            for {selectedDate ? formatUtcDate(selectedDate) : "today"}.
          </p>
          <ul aria-label="Launched products" className="launch-discovery-list">
            {items.map((item) => (
              <RankedLaunchCard
                identityClient={identityClient}
                item={item}
                key={item.product.id}
                launchDate={selectedDate ?? todayDate ?? ""}
                votingOpen={selectedDate === todayDate}
              />
            ))}
          </ul>
          {launches.hasNextPage ? (
            <div className="launch-discovery-more">
              <button
                className="launch-button launch-button-yellow"
                disabled={launches.isFetchingNextPage}
                onClick={() => void launches.fetchNextPage()}
                type="button"
              >
                {launches.isFetchingNextPage
                  ? "Loading more…"
                  : "Load more launches"}
              </button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

function shiftUtcDate(value: string, offset: number): string {
  const [year, month, day] = value.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, month - 1, day + offset));
  return shifted.toISOString().slice(0, 10);
}

function formatUtcDate(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "long",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}
