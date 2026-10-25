import type { PublicCatalogPage } from "./client";
import { PublicLaunchCard } from "./PublicLaunchCard";
import type { usePublicCatalog } from "./useLaunches";

type DiscoverResultsProps = {
  catalog: ReturnType<typeof usePublicCatalog>;
  items: PublicCatalogPage["items"];
  filtersValid: boolean;
  hasFilters: boolean;
  onClearFilters: () => void;
};

export function DiscoverResults({
  catalog,
  items,
  filtersValid,
  hasFilters,
  onClearFilters,
}: DiscoverResultsProps) {
  return (
    <section aria-labelledby="discover-results-title" className="launch-panel">
      <header className="launch-section-heading">
        <div>
          <p className="launch-kicker">PUBLIC AND LAUNCHED</p>
          <h2 id="discover-results-title">Launches</h2>
        </div>
        {catalog.data ? (
          <span className="launch-discover-count">
            {items.length} {items.length === 1 ? "result" : "results"}
          </span>
        ) : null}
      </header>

      {!filtersValid ? (
        <p className="launch-discovery-state" role="status">
          Correct the highlighted filters to load matching launches.
        </p>
      ) : catalog.isPending ? (
        <p className="launch-discovery-state" role="status">
          Loading launches…
        </p>
      ) : catalog.isError && items.length === 0 ? (
        <div className="launch-discovery-state launch-discovery-error">
          <p role="alert">
            Launches could not be loaded. Your filters are still here.
          </p>
          <button
            className="launch-button launch-button-yellow"
            disabled={catalog.isFetching}
            onClick={() => void catalog.refetch()}
            type="button"
          >
            {catalog.isFetching ? "Retrying…" : "Retry"}
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="launch-empty launch-discovery-empty">
          <span aria-hidden="true" className="launch-empty-mark">
            0
          </span>
          <div>
            <h3>
              {hasFilters
                ? "No launches match these filters"
                : "No launches yet"}
            </h3>
            <p>
              {hasFilters
                ? "Try a different search or remove a topic filter."
                : "Come back soon to discover newly published products."}
            </p>
          </div>
          {hasFilters ? (
            <button
              className="launch-button launch-button-yellow"
              onClick={onClearFilters}
              type="button"
            >
              Clear filters
            </button>
          ) : null}
        </div>
      ) : (
        <>
          <p className="sr-only" role="status">
            Showing {items.length} {items.length === 1 ? "launch" : "launches"}.
          </p>
          <ul aria-label="Catalog launches" className="launch-discovery-list">
            {items.map((item) => (
              <PublicLaunchCard item={item} key={item.id} />
            ))}
          </ul>
          {catalog.isError ? (
            <div
              className="launch-discovery-state launch-discovery-error"
              role="alert"
            >
              <p>
                More launches could not be loaded. Existing results are
                unchanged.
              </p>
              <button
                className="launch-button launch-button-yellow"
                disabled={catalog.isFetching}
                onClick={() => void catalog.fetchNextPage()}
                type="button"
              >
                Retry loading more
              </button>
            </div>
          ) : catalog.hasNextPage ? (
            <div className="launch-discovery-more">
              <button
                className="launch-button launch-button-yellow"
                disabled={catalog.isFetchingNextPage}
                onClick={() => void catalog.fetchNextPage()}
                type="button"
              >
                {catalog.isFetchingNextPage
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
