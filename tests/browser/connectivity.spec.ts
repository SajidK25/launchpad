import { expect, test } from "@playwright/test";

test("shows healthy, failed, and recovered API connectivity", async ({
  page,
}) => {
  await page.route("**/api/v1/health/ready", (route) =>
    route.fulfill({ json: { status: "ready" } }),
  );
  await expect(async () => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(
      page.getByText("Launchpad is temporarily unavailable."),
    ).toBeHidden();
    await expect(
      page.getByRole("heading", {
        name: "Fresh products. Every day.",
      }),
    ).toBeVisible();
  }).toPass({ timeout: 15_000 });

  await page.unroute("**/api/v1/health/ready");
  await page.route("**/api/v1/health/ready", (route) =>
    route.abort("connectionrefused"),
  );
  await page.reload();
  await expect(
    page.getByRole("heading", {
      name: "Fresh products. Every day.",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Create your account" }),
  ).toBeVisible();
  await expect(
    page.getByText("Launchpad is temporarily unavailable."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Check again" })).toBeVisible();

  await page.unroute("**/api/v1/health/ready");
  await page.route("**/api/v1/health/ready", (route) =>
    route.fulfill({ json: { status: "ready" } }),
  );
  await page.getByRole("button", { name: "Check again" }).click();
  await expect(
    page.getByText("Launchpad is temporarily unavailable."),
  ).toBeHidden();
});
