import { expect, test } from "@playwright/test";

test("Obsidian settings: directions, and a folder that isn't a vault is refused", async ({ page }) => {
  await page.goto("/settings?tab=obsidian");
  await expect(page.getByRole("heading", { name: "Obsidian" })).toBeVisible();
  await expect(page.getByText("Copy as Pathname")).toBeVisible();
  const connect = page.getByRole("button", { name: "Connect" });
  await expect(connect).toBeDisabled();
  await page.getByLabel("Obsidian vault folder").fill("/no/such/vault");
  await connect.click();
  await expect(page.getByText("There's no folder at /no/such/vault")).toBeVisible();
});
