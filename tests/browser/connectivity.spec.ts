import { expect, test } from "@playwright/test";

test("shows healthy, failed, and recovered API connectivity", async ({ page }) => {
  await expect(async () => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("status")).toHaveText("Connected");
  }).toPass({ timeout: 15_000 });

  await page.route("**/api/v1/health/ready", (route) => route.abort("connectionrefused"));
  await page.reload();
  await expect(page.getByRole("status")).toHaveText("Unavailable");
  await expect(page.getByRole("button", { name: "Check again" })).toBeVisible();

  await page.unroute("**/api/v1/health/ready");
  await page.getByRole("button", { name: "Check again" }).click();
  await expect(page.getByRole("status")).toHaveText("Connected");
});
