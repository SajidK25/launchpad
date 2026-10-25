import type { PublicCatalogTopicOptions } from "./client";
import type { usePublicCatalogTopics } from "./useLaunches";

const MAX_SEARCH_LENGTH = 200;
const MAX_SELECTED_TOPICS = 20;

type Topic = PublicCatalogTopicOptions["choices"][number];
type TopicQuery = ReturnType<typeof usePublicCatalogTopics>;

type DiscoverFiltersProps = {
  searchInput: string;
  topicQuery: string;
  topicIds: string[];
  topicLimitReached: boolean;
  topicOptions: TopicQuery;
  selectedTopics: Topic[];
  hasFilters: boolean;
  onSearchInputChange: (value: string) => void;
  onTopicQueryChange: (value: string) => void;
  onToggleTopic: (id: string) => void;
  onClearFilters: () => void;
};

export function DiscoverFilters({
  searchInput,
  topicQuery,
  topicIds,
  topicLimitReached,
  topicOptions,
  selectedTopics,
  hasFilters,
  onSearchInputChange,
  onTopicQueryChange,
  onToggleTopic,
  onClearFilters,
}: DiscoverFiltersProps) {
  const choices = topicOptions.data?.choices ?? [];

  return (
    <section aria-labelledby="discover-filters-title" className="launch-panel">
      <header className="launch-section-heading">
        <div>
          <p className="launch-kicker">FIND YOUR NEXT TOOL</p>
          <h2 id="discover-filters-title">Search and browse</h2>
        </div>
        {hasFilters ? (
          <button
            className="launch-button launch-button-outline"
            onClick={onClearFilters}
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
            onChange={(event) => onSearchInputChange(event.currentTarget.value)}
            placeholder="Name, pitch, or description"
            type="search"
            value={searchInput}
          />
          <span className="launch-discover-hint" id="discover-search-hint">
            All search terms must match. Up to {MAX_SEARCH_LENGTH} characters.
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
            onChange={(event) => onTopicQueryChange(event.currentTarget.value)}
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
        <ul aria-label="Selected topics" className="launch-discover-selected">
          {selectedTopics.map((topic) => (
            <li key={topic.id}>
              <span>{topic.displayName}</span>
              <button
                aria-label={`Remove ${topic.displayName}`}
                className="launch-discover-chip-remove"
                onClick={() => onToggleTopic(topic.id)}
                type="button"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {topicLimitReached || topicIds.length > MAX_SELECTED_TOPICS ? (
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
                  onClick={() => onToggleTopic(topic.id)}
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
  );
}
