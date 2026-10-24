/** @vitest-environment jsdom */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoverPage } from "./DiscoverPage";
import type { LaunchClient } from "./client";

const hooks = vi.hoisted(() => ({
  catalog: null as unknown,
  topics: null as unknown,
  catalogCalls: [] as unknown[][],
  topicCalls: [] as unknown[][],
}));

vi.mock("./useLaunches", () => ({
  usePublicCatalog: (...args: unknown[]) => {
    hooks.catalogCalls.push(args);
    return hooks.catalog;
  },
  usePublicCatalogTopics: (...args: unknown[]) => {
    hooks.topicCalls.push(args);
    return hooks.topics;
  },
}));

const firstProduct = {
  id: "product-1",
  name: "Alpha launch",
  pitch: "A searchable pitch",
  logoUrl: "/assets/alpha.png",
  topics: ["Developer tools"],
};

function page(
  items = [firstProduct],
  nextCursor: string | null = null,
  extraItems: (typeof firstProduct)[] = [],
) {
  return {
    pages: [
      { items, nextCursor },
      ...(extraItems.length > 0
        ? [{ items: extraItems, nextCursor: null }]
        : []),
    ],
  };
}

function catalogState(overrides: Record<string, unknown> = {}) {
  return {
    data: page(),
    isPending: false,
    isError: false,
    isFetching: false,
    isFetchingNextPage: false,
    hasNextPage: false,
    refetch: vi.fn(),
    fetchNextPage: vi.fn(),
    ...overrides,
  };
}

function topicState(choices: { id: string; displayName: string }[] = []) {
  return {
    data: { choices, selected: [] },
    isPending: false,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
  };
}

function renderDiscover() {
  return render(<DiscoverPage client={{} as LaunchClient} />);
}

beforeEach(() => {
  hooks.catalog = catalogState();
  hooks.topics = topicState([
    { id: "topic-1", displayName: "Developer tools" },
    { id: "topic-2", displayName: "Productivity" },
  ]);
  hooks.catalogCalls = [];
  hooks.topicCalls = [];
});

afterEach(cleanup);

describe("DiscoverPage", () => {
  it("shows public catalog cards and sends typed search filters to the query hook", () => {
    renderDiscover();

    expect(
      screen.getByRole("heading", { name: "Discover launches" }),
    ).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Alpha launch" })).toBeTruthy();
    expect(screen.getByText("A searchable pitch")).toBeTruthy();
    expect(screen.getAllByText("Developer tools")).toHaveLength(2);
    expect(screen.queryByText(/private description|private\.png/i)).toBeNull();
    expect(screen.getAllByRole("link", { name: /Alpha launch/ })).toHaveLength(
      2,
    );
    expect(hooks.catalogCalls.at(-1)?.slice(1)).toEqual(["", []]);

    fireEvent.change(
      screen.getByRole("searchbox", { name: /Search launches/ }),
      {
        target: { value: "  alpha   launch " },
      },
    );
    expect(hooks.catalogCalls.at(-1)?.slice(1)).toEqual([
      "  alpha   launch ",
      [],
    ]);
  });

  it("selects and removes multiple topics and enforces the twenty-topic maximum", () => {
    hooks.topics = topicState(
      Array.from({ length: 21 }, (_, index) => ({
        id: `topic-${String(index + 1).padStart(2, "0")}`,
        displayName: `Topic ${String(index + 1).padStart(2, "0")}`,
      })),
    );
    renderDiscover();

    for (let index = 1; index <= 20; index += 1) {
      fireEvent.click(
        screen.getByRole("button", {
          name: `Topic ${String(index).padStart(2, "0")}`,
        }),
      );
    }
    expect(
      screen.getByRole("list", { name: "Selected topics" }).children,
    ).toHaveLength(20);
    expect(hooks.catalogCalls.at(-1)?.[2]).toHaveLength(20);

    fireEvent.click(screen.getByRole("button", { name: "Topic 21" }));
    expect(screen.getByRole("alert").textContent).toContain("up to 20 topics");
    expect(hooks.catalogCalls.at(-1)?.[2]).toHaveLength(20);

    fireEvent.click(screen.getByRole("button", { name: "Remove Topic 01" }));
    expect(
      screen.getByRole("list", { name: "Selected topics" }).children,
    ).toHaveLength(19);
  });

  it("preserves valid results while reporting overlong search text", () => {
    renderDiscover();
    const search = screen.getByRole("searchbox", { name: /Search launches/ });

    fireEvent.change(search, { target: { value: "valid search" } });
    fireEvent.change(search, { target: { value: "x".repeat(201) } });

    expect(screen.getByRole("alert").textContent).toContain(
      "Shorten it to 200 characters",
    );
    expect(screen.getByRole("heading", { name: "Alpha launch" })).toBeTruthy();
    expect(hooks.catalogCalls.at(-1)?.[1]).toBe("valid search");
  });

  it("distinguishes an empty catalog from no matching results", () => {
    hooks.catalog = catalogState({ data: page([]) });
    const view = renderDiscover();
    expect(
      screen.getByRole("heading", { name: "No launches yet" }),
    ).toBeTruthy();

    fireEvent.change(
      screen.getByRole("searchbox", { name: /Search launches/ }),
      {
        target: { value: "no match" },
      },
    );
    hooks.catalog = catalogState({ data: page([]) });
    view.rerender(<DiscoverPage client={{} as LaunchClient} />);
    expect(
      screen.getByRole("heading", { name: "No launches match these filters" }),
    ).toBeTruthy();
    fireEvent.click(
      screen.getAllByRole("button", { name: "Clear filters" })[0]!,
    );
    expect(hooks.catalogCalls.at(-1)?.[1]).toBe("");
  });

  it("shows a retryable failure separately and keeps current filters", () => {
    const retry = vi.fn();
    hooks.catalog = catalogState({
      data: undefined,
      isError: true,
      refetch: retry,
    });
    renderDiscover();

    expect(screen.getByRole("alert").textContent).toContain(
      "could not be loaded",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("appends pages without duplicate cards and removes Load more at the end", () => {
    const fetchNextPage = vi.fn();
    hooks.catalog = catalogState({
      data: page([firstProduct], "cursor-next"),
      hasNextPage: true,
      fetchNextPage,
    });
    const view = renderDiscover();
    fireEvent.click(screen.getByRole("button", { name: "Load more launches" }));
    expect(fetchNextPage).toHaveBeenCalledOnce();

    hooks.catalog = catalogState({
      data: page([firstProduct], null, [
        firstProduct,
        { ...firstProduct, id: "product-2", name: "Beta launch" },
      ]),
    });
    view.rerender(<DiscoverPage client={{} as LaunchClient} />);
    expect(
      screen.getAllByRole("heading", { name: "Alpha launch" }),
    ).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Beta launch" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Load more/ })).toBeNull();
  });
});
