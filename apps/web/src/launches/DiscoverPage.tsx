import { useMemo, useState } from "react";
import type { LaunchClient, PublicCatalogPage } from "./client";
import { PublicLaunchCard } from "./PublicLaunchCard";
import { usePublicCatalog, usePublicCatalogTopics } from "./useLaunches";

const MAX_SEARCH_LENGTH = 200;
const MAX_SELECTED_TOPICS = 20;

export function DiscoverPage({ client }: { client: LaunchClient }) {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [topicQuery, setTopicQuery] = useState("");
  const [topicIds, setTopicIds] = useState<string[]>([]);
  const [topicLimitReached, setTopicLimitReached] = useState(false);
  const catalog = usePublicCatalog(client, search, topicIds);
  const topicOptions = usePublicCatalogTopics(client, topicQuery, topicIds);
  const items = useMemo(() => {
    const uniqueItems = new Map<string, PublicCatalogPage["items"][number]>();
    for (const page of catalog.data?.pages ?? [])
      for (const item of page.items) uniqueItems.set(item.id, item);
    return [...uniqueItems.values()];
  }, [catalog.data]);
  const selectedTopics = topicIds.map(
    (id) =>
      topicOptions.data?.selected.find((topic) => topic.id === id) ??
      topicOptions.data?.choices.find((topic) => topic.id === id) ?? {
        id,
        displayName: `Topic ${id.slice(0, 8)}`,
      },
  );
  const choices = topicOptions.data?.choices ?? [];
  const hasFilters = Boolean(search) || topicIds.length > 0;

  function updateSearch(value: string) {
    setSearchInput(value);
    if (value.length <= MAX_SEARCH_LENGTH) setSearch(value);
  }

  function toggleTopic(id: string) {
    setTopicLimitReached(false);
    if (topicIds.includes(id)) {
      setTopicIds((current) => current.filter((topicId) => topicId !== id));
      return;
    }
    if (topicIds.length >= MAX_SELECTED_TOPICS) {
      setTopicLimitReached(true);
      return;
    }
    setTopicIds((current) => [...current, id].sort());
  }

  function clearFilters() {
    setSearchInput("");
    setSearch("");
    setTopicIds([]);
    setTopicLimitReached(false);
  }

  return (
    <main className="launch-shell launch-discover-page">
      <div className="launch-workspace">
        <header className="launch-hero launch-discover-hero">
          <p className="launch-kicker">THE LAUNCHED CATALOG</p>
          <h1>Discover launches</h1>
          <p>
            Search every public launch by name, pitch, description, or topic.
          </p>
        </header>

        <section
          aria-labelledby="discover-filters-title"
          className="launch-panel"
        >
          <header className="launch-section-heading">
            <div>
              <p className="launch-kicker">FIND YOUR NEXT TOOL</p>
              <h2 id="discover-filters-title">Search and browse</h2>
            </div>
            {hasFilters ? (
              <button
                className="launch-button launch-button-outline"
                onClick={clearFilters}
                type="button"
              >
                Clear filters
              </button>
            ) : null}
          </header>

          <div className="launch-discover-filters">
            <label className="launch-discover-field">
              <span>Search launches</span>
              <input
                aria-describedby={
                  searchInput.length > MAX_SEARCH_LENGTH
                    ? "discover-search-hint discover-search-error"
                    : "discover-search-hint"
                }
                maxLength={MAX_SEARCH_LENGTH + 1}
                onChange={(event) => updateSearch(event.currentTarget.value)}
                placeholder="Name, pitch, or description"
                type="search"
                value={searchInput}
              />
              <span className="launch-discover-hint" id="discover-search-hint">
                All search terms must match. Up to {MAX_SEARCH_LENGTH}{" "}
                characters.
              </span>
              {searchInput.length > MAX_SEARCH_LENGTH ? (
                <span
                  className="launch-discover-validation"
                  id="discover-search-error"
                  role="alert"
                >
                  Search is too long. Shorten it to 200 characters; your current
                  results are preserved.
                </span>
              ) : null}
            </label>

            <div className="launch-discover-field">
              <label htmlFor="discover-topic-search">Browse topics</label>
              <input
                aria-controls="discover-topic-options"
                id="discover-topic-search"
                maxLength={MAX_SEARCH_LENGTH}
                onChange={(event) => setTopicQuery(event.currentTarget.value)}
                placeholder="Search public topics"
                type="search"
                value={topicQuery}
              />
              <span className="launch-discover-hint">
                Select up to {MAX_SELECTED_TOPICS} topics. Matching any selected
                topic includes a launch.
              </span>
            </div>
          </div>

          {selectedTopics.length > 0 ? (
            <ul
              aria-label="Selected topics"
              className="launch-discover-selected"
            >
              {selectedTopics.map((topic) => (
                <li key={topic.id}>
                  <span>{topic.displayName}</span>
                  <button
                    aria-label={`Remove ${topic.displayName}`}
                    className="launch-discover-chip-remove"
                    onClick={() => toggleTopic(topic.id)}
                    type="button"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          ) : null}

          {topicLimitReached ? (
            <p className="launch-discover-validation" role="alert">
              You can select up to 20 topics. Remove one before adding another.
            </p>
          ) : null}

          {topicOptions.isError ? (
            <div className="launch-discovery-state launch-discovery-error">
              <p role="alert">
                Topics could not be loaded. Your selected filters are unchanged.
              </p>
              <button
                className="launch-button launch-button-yellow"
                disabled={topicOptions.isFetching}
                onClick={() => void topicOptions.refetch()}
                type="button"
              >
                {topicOptions.isFetching ? "Retrying…" : "Retry topics"}
              </button>
            </div>
          ) : choices.length > 0 ? (
            <ul
              aria-label="Topic suggestions"
              className="launch-discover-options"
              id="discover-topic-options"
            >
              {choices.map((topic) => {
                const selected = topicIds.includes(topic.id);
                return (
                  <li key={topic.id}>
                    <button
                      aria-pressed={selected}
                      className="launch-discover-option"
                      onClick={() => toggleTopic(topic.id)}
                      type="button"
                    >
                      <span aria-hidden="true">{selected ? "✓" : "+"}</span>
                      {topic.displayName}
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : topicQuery && !topicOptions.isPending ? (
            <p className="launch-discover-hint" role="status">
              No matching public topics.
            </p>
          ) : null}
        </section>

        <section
          aria-labelledby="discover-results-title"
          className="launch-panel"
        >
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

          {catalog.isPending ? (
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
                  onClick={clearFilters}
                  type="button"
                >
                  Clear filters
                </button>
              ) : null}
            </div>
          ) : (
            <>
              <p className="sr-only" role="status">
                Showing {items.length}{" "}
                {items.length === 1 ? "launch" : "launches"}.
              </p>
              <ul
                aria-label="Catalog launches"
                className="launch-discovery-list"
              >
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
      </div>
    </main>
  );
}
