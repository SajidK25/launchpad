/** @vitest-environment jsdom */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  Action,
  EmptyState,
  LoadingState,
  PageHeading,
  Pagination,
  Panel,
  StatusBanner,
  UnavailableState,
} from "./Primitives";

afterEach(cleanup);

describe("PageHeading", () => {
  it("keeps actions outside the page title heading", () => {
    render(
      <PageHeading
        title="Your products"
        description="Manage your submissions."
        actions={<button type="button">New product</button>}
      />,
    );

    expect(
      screen.getByRole("heading", { level: 1, name: "Your products" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "New product" }).closest("h1"),
    ).toBeNull();
  });
});

describe("Panel", () => {
  it("uses the requested section or article semantics without adding a main landmark", () => {
    render(
      <>
        <main>
          <Panel as="article" title="Submission details">
            Product details
          </Panel>
        </main>
      </>,
    );

    expect(screen.getByRole("article")).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Submission details" }),
    ).toBeTruthy();
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });
});

describe("Action", () => {
  it("renders navigation as an anchor and commands as safe buttons", () => {
    render(
      <>
        <Action href="/products">Your products</Action>
        <Action onClick={() => undefined}>Create product</Action>
        <Action disabled onClick={() => undefined}>
          Save
        </Action>
      </>,
    );

    expect(
      screen.getByRole("link", { name: "Your products" }).getAttribute("href"),
    ).toBe("/products");
    expect(
      screen
        .getByRole("button", { name: "Create product" })
        .getAttribute("type"),
    ).toBe("button");
    expect(
      (screen.getByRole("button", { name: "Save" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });
});

describe("Pagination", () => {
  it("labels the position, disables unavailable directions, and calls enabled handlers", () => {
    const onPrevious = vi.fn();
    const onNext = vi.fn();
    render(
      <Pagination
        page={1}
        pageCount={3}
        onPrevious={onPrevious}
        onNext={onNext}
      />,
    );

    const navigation = screen.getByRole("navigation", { name: "Pagination" });
    expect(navigation.textContent).toContain("Page 1 of 3");
    expect(
      (
        screen.getByRole("button", {
          name: "Previous page",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: "Next page" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(onPrevious).not.toHaveBeenCalled();
    expect(onNext).toHaveBeenCalledOnce();
  });
});

describe("state primitives", () => {
  it("keeps status text visible and maps warning/error to alert semantics", () => {
    render(
      <>
        <StatusBanner variant="warning">
          Review is taking longer than usual.
        </StatusBanner>
        <StatusBanner variant="info">Your profile is up to date.</StatusBanner>
      </>,
    );

    expect(screen.getByRole("alert").textContent).toContain(
      "Review is taking longer",
    );
    expect(screen.getByRole("status").textContent).toContain(
      "Your profile is up to date",
    );
  });

  it("provides contextual loading, empty, and unavailable states with optional recovery", () => {
    render(
      <>
        <LoadingState
          title="Loading products"
          description="This may take a moment."
        />
        <EmptyState
          title="No products yet"
          description="Create your first submission."
        />
        <UnavailableState
          title="Calendar unavailable"
          description="Try again shortly."
        />
        <UnavailableState
          title="Inbox unavailable"
          description="Your messages are safe."
          action={<button type="button">Retry inbox</button>}
        />
      </>,
    );

    expect(screen.getByRole("status").textContent).toContain(
      "This may take a moment",
    );
    expect(
      screen.getByRole("heading", { name: "No products yet" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Calendar unavailable" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry inbox" })).toBeTruthy();
  });
});
