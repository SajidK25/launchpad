/** @vitest-environment jsdom */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { DailyRankingItem } from "../launches/client";
import { RankedLaunchCard } from "./RankedLaunchCard";

const item: DailyRankingItem = {
  product: {
    id: "product-1",
    name: "Launchpad demo",
    pitch: "A public launch pitch",
    logoUrl: "/assets/logo.png",
    topics: ["Developer tools", "Productivity"],
  },
  rank: 1,
  activeVoteCount: 0,
  score: 0,
  viewerVoted: null,
};

afterEach(cleanup);

describe("RankedLaunchCard", () => {
  it("shows rank, zero-vote count, and launched public product details", () => {
    render(<RankedLaunchCard item={item} />);

    expect(screen.getByText("RANK #1")).toBeTruthy();
    expect(screen.getByText("0 votes")).toBeTruthy();
    expect(screen.getByText("A public launch pitch")).toBeTruthy();
    expect(screen.getByText("Developer tools")).toBeTruthy();
    expect(
      screen
        .getByRole("heading", { name: "Launchpad demo" })
        .querySelector("a")
        ?.getAttribute("href"),
    ).toBe("/launches/product-1");
    expect(screen.queryByText(/score|viewerVoted|private/i)).toBeNull();
  });

  it("marks pre-voting archive entries as unranked without fabricated votes", () => {
    render(
      <RankedLaunchCard
        item={{ ...item, rank: null, activeVoteCount: null, score: null }}
      />,
    );

    expect(screen.getByText("UNRANKED")).toBeTruthy();
    expect(screen.queryByText(/votes?/i)).toBeNull();
  });
});
