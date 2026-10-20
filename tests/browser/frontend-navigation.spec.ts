import { expect, test, type Page } from "@playwright/test";

const notice = {
  id: "00000000-0000-4000-8000-000000000001",
  productId: "00000000-0000-4000-8000-000000000002",
  kind: "REVIEW_APPROVED",
  createdAt: "2026-10-19T12:00:00Z",
  readAt: null,
};

async function installFixtures(page: Page) {
  let role: "member" | "reviewer" = "member";
  let authenticated = true;
  let inboxItems: (typeof notice)[] = [];
  await page.route("**/api/v1/auth/session", (route) => {
    if (!authenticated)
      return route.fulfill({
        status: 401,
        json: { detail: "Not authenticated" },
      });
    return route.fulfill({
      json: {
        account_id: "browser-fixture-account",
        csrf_token: "browser-fixture-token",
        role,
        verified: true,
        suspended: false,
      },
    });
  });
  await page.route("**/api/v1/health/ready", (route) =>
    route.fulfill({ json: { status: "ready" } }),
  );
  await page.route("**/api/v1/graphql", (route) => {
    const request = route.request().postDataJSON() as { query: string };
    const query = request.query;
    const emptyPage = { items: [], nextCursor: null };
    let data: Record<string, unknown> = {};
    if (query.includes("viewerProducts")) data = { viewerProducts: emptyPage };
    else if (query.includes("reviewQueue")) data = { reviewQueue: emptyPage };
    else if (query.includes("approvedReviews"))
      data = { approvedReviews: emptyPage };
    else if (query.includes("viewerLaunchBookings"))
      data = { viewerLaunchBookings: emptyPage };
    else if (query.includes("viewerLaunchNotificationPreferences"))
      data = {
        viewerLaunchNotificationPreferences: {
          reminderEmail: true,
          reminderInSite: true,
          liveEmail: true,
          liveInSite: true,
          failureEmail: true,
          failureInSite: true,
        },
      };
    else if (query.includes("viewerNotificationInbox"))
      data = {
        viewerNotificationInbox: {
          items: inboxItems,
          unreadCount: inboxItems.filter((item) => !item.readAt).length,
          nextCursor: null,
        },
      };
    else if (query.includes("viewerProduct")) data = { viewerProduct: null };
    else if (query.includes("publicProfile")) data = { publicProfile: null };
    else if (query.includes("publicProduct")) data = { publicProduct: null };
    else if (query.includes("topicChoices")) data = { topicChoices: [] };
    return route.fulfill({ json: { data } });
  });
  await page.route("**/api/v1/me/notifications/*/read", (route) =>
    route.fulfill({
      json: {
        ...notice,
        kind: "review_approved",
        product_id: notice.productId,
        created_at: notice.createdAt,
        read_at: "2026-10-19T12:01:00Z",
      },
    }),
  );
  await page.routeWebSocket("**/api/v1/me/notifications/live", (socket) => {
    socket.close();
  });

  return {
    setRole(value: "member" | "reviewer") {
      role = value;
    },
    setAuthenticated(value: boolean) {
      authenticated = value;
    },
    setInboxItems(items: (typeof notice)[]) {
      inboxItems = items;
    },
  };
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
}

test("founder navigation, notification destination focus, and 320px layout work", async ({
  page,
}) => {
  const fixtures = await installFixtures(page);
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto("/products");

  await expect(
    page.getByRole("button", { name: /Notifications.*0 unread/ }),
  ).toHaveCount(1);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expectNoHorizontalOverflow(page);

  const menuButton = page.getByRole("button", { name: "Open workspace menu" });
  await menuButton.click();
  await expect(page.getByRole("link", { name: "Your products" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menuButton).toBeFocused();

  fixtures.setInboxItems([notice]);
  await page.reload();
  await page.getByRole("button", { name: /Notifications.*1 unread/ }).click();
  await page.getByRole("button", { name: "Approval received, unread" }).click();
  await expect(page).toHaveURL(
    /\/products\/00000000-0000-4000-8000-000000000002$/,
  );
  await expect(
    page.getByRole("heading", { name: "Product unavailable" }),
  ).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => document.activeElement?.id))
    .toBe("product-main");
  await expectNoHorizontalOverflow(page);
});

test("reviewer shell shows its queue without founder-only navigation", async ({
  page,
}) => {
  const fixtures = await installFixtures(page);
  fixtures.setRole("reviewer");
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto("/products/review");

  await expect(
    page.getByRole("button", { name: "Open workspace menu" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open workspace menu" }).click();
  await expect(
    page.getByRole("navigation", { name: "Reviewer workspace" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Staff review queue" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Notifications/ })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("navigation", { name: "Reviewer workspace" }),
  ).toContainText("Decision history");
  await expectNoHorizontalOverflow(page);
});

test("session loss gates private routes and 200% zoom keeps actions in view", async ({
  page,
}) => {
  const fixtures = await installFixtures(page);
  fixtures.setAuthenticated(false);
  await page.goto("/products");
  await expect(
    page.getByRole("heading", { name: "Sign in to continue" }),
  ).toBeVisible();
  await expect(page.getByText("Fixture private product")).toHaveCount(0);

  fixtures.setAuthenticated(true);
  await page.setViewportSize({ width: 640, height: 900 });
  await page.goto("/launches");
  await page.evaluate(() => {
    document.documentElement.style.zoom = "200%";
  });
  await expect(
    page.getByRole("heading", { name: "Your launch calendar" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Launch notifications" }),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(
    page.getByRole("link", { name: "Manage product details ↗" }),
  ).toBeVisible();
});

test("unpublished public launch paths show a safe unavailable page", async ({
  page,
}) => {
  await installFixtures(page);
  await page.goto("/launches/00000000-0000-4000-8000-000000000099");
  await expect(
    page.getByRole("heading", { name: "Launch not found" }),
  ).toBeVisible();
  await expect(
    page.getByText("This launch is private or unavailable."),
  ).toBeVisible();
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByText("private review feedback")).toHaveCount(0);
});
