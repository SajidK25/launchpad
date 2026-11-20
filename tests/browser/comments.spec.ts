import { expect, test, type Page } from "@playwright/test";

const product = {
  id: "00000000-0000-4000-8000-000000000101",
  name: "Threadline",
  pitch: "A calmer place for product feedback",
  description: "Collect thoughtful launch-day feedback without losing context.",
  websiteUrl: "https://example.com",
  launchedAt: "2026-11-20T00:00:00Z",
  logo: null,
  screenshots: [],
  topics: ["Community"],
};

async function installFixtures(page: Page) {
  let signedIn = false;
  await page.route("**/api/v1/health/ready", (route) =>
    route.fulfill({ json: { status: "ready" } }),
  );
  await page.route("**/api/v1/auth/session", (route) =>
    signedIn
      ? route.fulfill({
          json: {
            account_id: "00000000-0000-4000-8000-000000000201",
            csrf_token: "browser-csrf",
            role: "member",
            verified: true,
            suspended: false,
          },
        })
      : route.fulfill({ status: 401, json: { detail: "Not authenticated" } }),
  );
  await page.route("**/api/v1/graphql", (route) => {
    const body = route.request().postDataJSON() as { query: string };
    let data: Record<string, unknown> = {};
    if (body.query.includes("ProductDiscussion")) {
      data = {
        productDiscussion: {
          items: [
            {
              id: "00000000-0000-4000-8000-000000000301",
              productId: product.id,
              parentId: null,
              body: "<strong>This remains plain text.</strong>",
              createdAt: "2026-11-20T08:00:00Z",
              author: {
                accountId: "00000000-0000-4000-8000-000000000202",
                displayName: "Demo member",
                avatarUrl: "/api/v1/demo-avatar",
                publicProfileUrl: null,
              },
              replyCount: 0,
              replies: [],
            },
          ],
          nextCursor: null,
        },
      };
    } else if (body.query.includes("ViewerProfile")) {
      data = {
        viewerProfile: {
          accountId: "00000000-0000-4000-8000-000000000201",
          displayName: "Browser member",
          bio: "",
          links: [],
          photoUrl: "/api/v1/demo-avatar",
          visibility: "private",
          version: 1,
        },
      };
    } else if (body.query.includes("DailyProductRanking")) {
      data = {
        dailyProductRanking: {
          todayDate: "2026-11-20",
          selectedDate: "2026-11-20",
          hasSnapshot: false,
          items: [],
          nextCursor: null,
        },
      };
    } else if (body.query.includes("PublicProduct")) {
      data = { publicProduct: product };
    }
    return route.fulfill({ json: { data } });
  });
  await page.route("**/comments/live-ticket", (route) =>
    route.fulfill({
      json: { ticket: "browser-ticket", expires_at: "2026-11-20T10:00:00Z" },
    }),
  );
  await page.route("**/api/v1/demo-avatar", (route) =>
    route.fulfill({ status: 204 }),
  );
  await page.route("**/api/v1/products/*/comments", (route) =>
    route.fulfill({
      status: 201,
      json: {
        id: "00000000-0000-4000-8000-000000000302",
        product_id: product.id,
        parent_id: null,
        body: "Keyboard-posted feedback",
        created_at: "2026-11-20T09:00:00Z",
        replayed: false,
      },
    }),
  );
  await page.routeWebSocket("**/api/v1/comments/live?**", () => {});
  await page.routeWebSocket("**/api/v1/votes/live?**", () => {});

  return {
    signIn: () => {
      signedIn = true;
    },
  };
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    )
    .toBe(true);
}

test("discussion stays public, keyboard-operable, safe, and responsive", async ({
  page,
}, testInfo) => {
  const fixtures = await installFixtures(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/launches/${product.id}`);

  await expect(page.getByRole("heading", { name: "Discussion" })).toBeVisible();
  await expect(
    page.getByText("<strong>This remains plain text.</strong>"),
  ).toBeVisible();
  await expect(page.locator(".comments-entry strong")).toHaveText(
    "Demo member",
  );
  await expect(
    page.getByRole("link", { name: "Sign in" }).last(),
  ).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Add to the discussion" }),
  ).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  const mobileScreenshot = testInfo.outputPath(
    "signed-out-mobile-discussion.png",
  );
  await page.screenshot({ fullPage: true, path: mobileScreenshot });
  await testInfo.attach("signed-out-mobile-discussion", {
    path: mobileScreenshot,
    contentType: "image/png",
  });

  fixtures.signIn();
  await page.reload();
  const composer = page.getByRole("textbox", { name: "Add to the discussion" });
  await expect(composer).toBeVisible();
  await composer.focus();
  await page.keyboard.type("Keyboard-posted feedback");
  await composer.press("Tab");
  const publish = page.getByRole("button", { name: "Publish" });
  await expect(publish).toBeFocused();

  await page.setViewportSize({ width: 1280, height: 900 });
  await expectNoHorizontalOverflow(page);
  await expect(page.getByRole("heading", { name: "Threadline" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Discussion" })).toBeVisible();
  const desktopScreenshot = testInfo.outputPath(
    "eligible-desktop-discussion.png",
  );
  await page.screenshot({ fullPage: true, path: desktopScreenshot });
  await testInfo.attach("eligible-desktop-discussion", {
    path: desktopScreenshot,
    contentType: "image/png",
  });
});
