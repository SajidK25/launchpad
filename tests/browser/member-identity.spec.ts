import { expect, test } from "@playwright/test";

test("account routes expose accessible sign-in and generic recovery paths", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await page.route("**/api/v1/auth/session", (route) =>
    route.fulfill({ status: 401, json: { detail: "Not authenticated" } }),
  );
  await page.route("**/api/v1/health/ready", (route) =>
    route.fulfill({ json: { status: "ready" } }),
  );
  await page.route("**/api/v1/graphql", (route) => {
    const request = route.request().postDataJSON() as { query: string };
    if (request.query.includes("publicProfile"))
      return route.fulfill({ json: { data: { publicProfile: null } } });
    return route.continue();
  });
  await page.goto("/signin", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("main")).toHaveCount(1);
  await page.getByLabel("Email").focus();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Password")).toBeFocused();
  await page.getByRole("link", { name: "Create an account" }).click();
  await expect(
    page.getByRole("heading", { name: "Create your account" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Back to sign in" }).click();
  await page.getByRole("link", { name: "Forgot your password?" }).click();
  await expect(
    page.getByRole("heading", { name: "Recover your account" }),
  ).toBeVisible();
  await expect(page.getByText(/never reveal account existence/)).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/signin", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.goto("/profile", { waitUntil: "domcontentloaded" });
  await page.goto("/public/not-public", { waitUntil: "domcontentloaded" });
  await expect(
    page.getByText("This profile is private or unavailable."),
  ).toBeVisible();
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(
    page.getByRole("heading", {
      name: "Take your product from ready to released.",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "Take your product from ready to released.",
    }),
  ).toBeVisible();
});
