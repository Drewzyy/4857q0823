import { expect, test } from "@playwright/test";

test("Chrome extension card: not connected until the extension checks in, with the folder to load", async ({ page }) => {
  await page.goto("/settings?tab=muse");
  await expect(page.getByRole("heading", { name: "Chrome extension: Vyral Companion" })).toBeVisible();
  await expect(page.getByRole("status", { name: "Chrome extension status" })).toContainText("Not connected");
  await expect(page.locator("code", { hasText: "chrome-extension" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy path" })).toBeEnabled();
});
