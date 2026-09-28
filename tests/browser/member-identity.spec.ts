import { expect, test } from "@playwright/test";

test("account routes expose accessible sign-in and generic recovery paths", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/signin", { waitUntil: "domcontentloaded" });
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
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/signin", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.goto("/profile", { waitUntil: "domcontentloaded" });
  await page.goto("/public/not-public", { waitUntil: "domcontentloaded" });
  await expect(
    page.getByText("This profile is private or unavailable."),
  ).toBeVisible();
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("status")).toHaveText("Connected");
});
