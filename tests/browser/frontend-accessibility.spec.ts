import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function installFixtures(page: Page) {
  let role: "member" | "reviewer" = "member";
  let signedIn = true;
  await page.route("**/api/v1/health/ready", (route) =>
    route.fulfill({ json: { status: "ready" } }),
  );
  await page.route("**/api/v1/auth/session", (route) => {
    if (!signedIn) {
      return route.fulfill({
        status: 401,
        json: { detail: "Not authenticated" },
      });
    }
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
          reminderInSite: false,
          liveEmail: true,
          liveInSite: false,
          failureEmail: true,
          failureInSite: false,
        },
      };
    else if (query.includes("viewerNotificationInbox"))
      data = { viewerNotificationInbox: { ...emptyPage, unreadCount: 0 } };
    else if (query.includes("viewerProfile"))
      data = {
        viewerProfile: {
          accountId: "browser-fixture-account",
          displayName: "Fixture founder",
          bio: "A founder profile for accessibility checks.",
          links: ["https://example.com"],
          photoUrl: null,
          visibility: "private",
          version: 1,
        },
      };
    else if (query.includes("publicProfile")) data = { publicProfile: null };
    else if (query.includes("publicProduct")) data = { publicProduct: null };
    else if (query.includes("viewerProduct")) data = { viewerProduct: null };
    else if (query.includes("topicChoices")) data = { topicChoices: [] };
    return route.fulfill({ json: { data } });
  });
  await page.routeWebSocket("**/api/v1/me/notifications/live", (socket) => {
    socket.close();
  });

  return {
    setRole(value: "member" | "reviewer") {
      role = value;
    },
    setSignedIn(value: boolean) {
      signedIn = value;
    },
  };
}

async function expectNoSeriousAccessibilityIssues(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map(({ id, impact, help, nodes }) => ({
      id,
      impact,
      help,
      elements: nodes.map(({ target }) => target),
    })),
  ).toEqual([]);
}

test("representative public, account, founder, reviewer, and launch pages pass axe", async ({
  page,
}) => {
  const fixtures = await installFixtures(page);

  fixtures.setSignedIn(false);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /Take your product/ }),
  ).toBeVisible();
  await expectNoSeriousAccessibilityIssues(page);

  for (const path of ["/signin", "/register", "/recover"]) {
    await page.goto(path);
    await expect(page.getByRole("heading")).toBeVisible();
    await expectNoSeriousAccessibilityIssues(page);
  }

  fixtures.setSignedIn(true);
  fixtures.setRole("member");
  await page.goto("/products");
  await expect(
    page.getByRole("heading", { name: "Your products" }),
  ).toBeVisible();
  await expectNoSeriousAccessibilityIssues(page);

  await page.goto("/profile");
  await expect(
    page.getByRole("heading", { name: "Your profile" }),
  ).toBeVisible();
  await expectNoSeriousAccessibilityIssues(page);

  fixtures.setRole("reviewer");
  await page.goto("/products/review");
  await expect(
    page.getByRole("heading", { name: "Staff review queue" }),
  ).toBeVisible();
  await expectNoSeriousAccessibilityIssues(page);

  fixtures.setRole("member");
  await page.goto("/launches");
  await expect(
    page.getByRole("heading", { name: "Your launch calendar" }),
  ).toBeVisible();
  await expectNoSeriousAccessibilityIssues(page);

  fixtures.setSignedIn(false);
  await page.goto("/launches/private-product");
  await expect(
    page.getByRole("heading", { name: "Launch not found" }),
  ).toBeVisible();
  await expectNoSeriousAccessibilityIssues(page);
});
