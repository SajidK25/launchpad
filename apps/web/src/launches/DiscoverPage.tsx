import { useLayoutEffect, useMemo, useState } from "react";
import type { LaunchClient, PublicCatalogPage } from "./client";
import { DiscoverFilters } from "./DiscoverFilters";
import { DiscoverResults } from "./DiscoverResults";
import { usePublicCatalog, usePublicCatalogTopics } from "./useLaunches";

const MAX_SEARCH_LENGTH = 200;
const MAX_SELECTED_TOPICS = 20;
const EMPTY_TOPIC_IDS: string[] = [];

type DiscoverPageProps = {
  client: LaunchClient;
  initialSearch?: string;
  initialTopicIds?: string[];
  onSearchChange?: (search: string) => void;
  onTopicIdsChange?: (topicIds: string[]) => void;
};

export function DiscoverPage({
  client,
  initialSearch = "",
  initialTopicIds = EMPTY_TOPIC_IDS,
  onSearchChange,
  onTopicIdsChange,
}: DiscoverPageProps) {
  const [localSearchInput, setLocalSearchInput] = useState(initialSearch);
  const [localSearch, setLocalSearch] = useState(
    initialSearch.length <= MAX_SEARCH_LENGTH ? initialSearch : "",
  );
  const [invalidSearchDraft, setInvalidSearchDraft] = useState<string | null>(
    null,
  );
  const [topicQuery, setTopicQuery] = useState("");
  const [localTopicIds, setLocalTopicIds] = useState(initialTopicIds);
  const [topicLimitReached, setTopicLimitReached] = useState(
    initialTopicIds.length > MAX_SELECTED_TOPICS,
  );
  const searchInput =
    invalidSearchDraft ?? (onSearchChange ? initialSearch : localSearchInput);
  const search = onSearchChange
    ? initialSearch.length <= MAX_SEARCH_LENGTH
      ? initialSearch
      : ""
    : localSearch;
  const topicIds = onTopicIdsChange ? initialTopicIds : localTopicIds;
  const filtersValid =
    topicIds.length <= MAX_SELECTED_TOPICS &&
    (searchInput.length <= MAX_SEARCH_LENGTH || Boolean(search));
  const catalog = usePublicCatalog(
    client,
    search,
    topicIds.length <= MAX_SELECTED_TOPICS ? topicIds : [],
    20,
    filtersValid,
  );
  const topicOptions = usePublicCatalogTopics(
    client,
    topicQuery,
    topicIds.length <= MAX_SELECTED_TOPICS ? topicIds : [],
  );
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
  const hasFilters = Boolean(search) || topicIds.length > 0;
  const initialTopicIdsKey = initialTopicIds.join("\u0000");

  useLayoutEffect(() => {
    setInvalidSearchDraft(null);
    setLocalSearchInput(initialSearch);
    setLocalSearch(
      initialSearch.length <= MAX_SEARCH_LENGTH ? initialSearch : "",
    );
  }, [initialSearch, initialTopicIdsKey]);

  function updateSearch(value: string) {
    setLocalSearchInput(value);
    if (value.length <= MAX_SEARCH_LENGTH) {
      setInvalidSearchDraft(null);
      setLocalSearch(value);
      onSearchChange?.(value);
    } else {
      setInvalidSearchDraft(value);
    }
  }

  function toggleTopic(id: string) {
    setTopicLimitReached(false);
    if (topicIds.includes(id)) {
      const nextTopicIds = topicIds.filter((topicId) => topicId !== id);
      setLocalTopicIds(nextTopicIds);
      onTopicIdsChange?.(nextTopicIds);
      return;
    }
    if (topicIds.length >= MAX_SELECTED_TOPICS) {
      setTopicLimitReached(true);
      return;
    }
    const nextTopicIds = [...topicIds, id].sort();
    setLocalTopicIds(nextTopicIds);
    onTopicIdsChange?.(nextTopicIds);
  }

  function clearFilters() {
    setLocalSearchInput("");
    setLocalSearch("");
    setInvalidSearchDraft(null);
    setLocalTopicIds([]);
    setTopicLimitReached(false);
    onSearchChange?.("");
    onTopicIdsChange?.([]);
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
        <DiscoverFilters
          hasFilters={hasFilters}
          onClearFilters={clearFilters}
          onSearchInputChange={updateSearch}
          onToggleTopic={toggleTopic}
          onTopicQueryChange={setTopicQuery}
          searchInput={searchInput}
          selectedTopics={selectedTopics}
          topicIds={topicIds}
          topicLimitReached={topicLimitReached}
          topicOptions={topicOptions}
          topicQuery={topicQuery}
        />
        <DiscoverResults
          catalog={catalog}
          filtersValid={filtersValid}
          hasFilters={hasFilters}
          items={items}
          onClearFilters={clearFilters}
        />
      </div>
    </main>
  );
}
