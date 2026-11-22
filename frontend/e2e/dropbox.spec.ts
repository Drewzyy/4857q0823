import { expect, test } from "@playwright/test";

test("Dropbox settings: setup steps, then waiting for the browser sign-in", async ({ page }) => {
  await page.goto("/settings?tab=dropbox");
  await expect(page.getByRole("heading", { name: "Dropbox" })).toBeVisible();
  await expect(page.getByText("http://127.0.0.1:53682/")).toBeVisible();
  const connect = page.getByRole("button", { name: "Connect" });
  await expect(connect).toBeDisabled();
  await page.getByLabel("Dropbox app key").fill("abc123def456ghi");
  await connect.click();
  await expect(page.getByText("Finish signing in on Dropbox's page")).toBeVisible();
  await expect(page.getByRole("link", { name: /open it here/ })).toHaveAttribute("href", /code_challenge_method=S256/);
});
