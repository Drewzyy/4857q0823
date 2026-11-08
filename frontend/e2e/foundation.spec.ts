import { expect, test, type Page } from "@playwright/test";

async function dragRoute(page: Page, from: string, to: string) {
  const handle = page.locator(".react-flow__node", { hasText: from }).locator(".react-flow__handle-right");
  const target = page.locator(".react-flow__node", { hasText: to });
  const a = (await handle.boundingBox())!;
  const b = (await target.boundingBox())!;
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + 20, b.y + b.height / 2, { steps: 12 });
  await page.mouse.move(b.x + 12, b.y + b.height / 2, { steps: 3 });
  await page.mouse.up();
}

test("accounts, funnel and settings work end to end and persist", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Get started")).toBeVisible();
  await expect(page.getByText("Running locally")).toBeVisible();

  // --- creators + sources
  await page.getByRole("navigation").getByRole("link", { name: "Source Accounts" }).click();
  for (const name of ["Streamer A", "Streamer B"]) {
    await page.getByRole("button", { name: "New creator" }).click();
    await page.getByLabel("Streamer / creator name").fill(name);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.locator(".filter-btn", { hasText: name })).toBeVisible();
  }
  await page.getByRole("button", { name: "Add account" }).first().click();
  await page.getByLabel("Username or profile link").fill("https://www.tiktok.com/@streamera.clips");
  await expect(page.getByText("Detected a tiktok link.")).toBeVisible();
  await page.getByLabel("Creator", { exact: true }).selectOption({ label: "Streamer A" });
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("cell", { name: /@streamera\.clips/ })).toBeVisible();

  // invalid input shows a clear error
  await page.getByRole("button", { name: "Add account" }).first().click();
  await page.getByLabel("Username or profile link").fill("https://vm.tiktok.com/abc/");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText(/short links can't be read offline/i)).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();

  // bulk import
  await page.getByRole("button", { name: "Import" }).click();
  await page.getByLabel("Paste handles or profile links, one per line").fill("@streamerb.clips\n@streamera.clips\nbad name!");
  await page.getByLabel("Assign to creator").selectOption({ label: "Streamer B" });
  await page.getByRole("button", { name: "Import list" }).click();
  await expect(page.getByText("1 added")).toBeVisible();
  await expect(page.getByText(/1 already present, 1 skipped/)).toBeVisible();
  await page.getByRole("button", { name: "Done" }).click();

  // pause monitoring, filter
  await page.getByRole("switch", { name: "Monitor streamerb.clips" }).click();
  await page.getByRole("button", { name: "Paused", exact: true }).click();
  await expect(page.getByRole("cell", { name: /@streamerb\.clips/ })).toBeVisible();
  await expect(page.getByRole("cell", { name: /@streamera\.clips/ })).toHaveCount(0);
  await page.getByRole("button", { name: "All", exact: true }).click();

  // --- destinations (planned, since no platform logins exist in CI)
  await page.getByRole("navigation").getByRole("link", { name: "Destination Accounts" }).click();
  for (const [plat, name, creator] of [["TikTok", "Streamer A TikTok", "Streamer A"], ["YouTube", "Streamer A YouTube", "Streamer A"], ["TikTok", "Streamer B TikTok", "Streamer B"]]) {
    await page.getByRole("button", { name: "Plan without logging in" }).click();
    await page.getByLabel("Platform").selectOption({ label: plat });
    await page.getByLabel("Name").fill(name);
    await page.getByLabel("Creator").selectOption({ label: creator });
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByText(name, { exact: true })).toBeVisible();
  }

  // per-destination settings persist
  await page.locator(".card", { hasText: "Streamer A YouTube" }).getByRole("button", { name: "Settings" }).click();
  await page.getByLabel("Hashtags").fill("gaming #clips");
  await page.getByLabel("Frame rate").selectOption("60");
  await page.getByRole("button", { name: "Add slot" }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Settings saved")).toBeVisible();
  await page.reload();
  await page.locator(".card", { hasText: "Streamer A YouTube" }).getByRole("button", { name: "Settings" }).click();
  await expect(page.getByLabel("Hashtags")).toHaveValue("#gaming #clips");
  await expect(page.getByLabel("Frame rate")).toHaveValue("60");
  await expect(page.getByLabel("Weekday")).toHaveCount(1);
  await page.getByRole("button", { name: "Cancel" }).click();

  // connect without setup opens the guided one-time setup with the exact redirect to copy
  await page.locator(".card", { hasText: "Facebook & Instagram" }).getByRole("button", { name: "Connect" }).click();
  await expect(page.getByRole("heading", { name: /One-time Facebook & Instagram setup/ })).toBeVisible();
  await expect(page.locator(".copybox code")).toHaveText("http://127.0.0.1:8799/oauth/callback/meta");
  await expect(page.getByRole("button", { name: "Continue to Facebook & Instagram login" })).toBeDisabled();
  await page.getByRole("button", { name: "Cancel" }).click();

  // --- funnel
  await page.getByRole("navigation").getByRole("link", { name: "Account Funnel" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(5);
  await dragRoute(page, "@streamera.clips", "Streamer A TikTok");
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);

  // cross-creator link asks for confirmation
  await dragRoute(page, "@streamerb.clips", "Streamer A YouTube");
  await expect(page.getByRole("heading", { name: "Mix creators?" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);

  await page.getByRole("button", { name: "Auto-route by creator" }).click();
  await expect(page.getByText(/Created 2 route/)).toBeVisible();
  await expect(page.locator(".react-flow__edge")).toHaveCount(3);

  // routing preview for a source
  await page.locator(".react-flow__node", { hasText: "@streamera.clips" }).click();
  const preview = page.locator(".card", { hasText: "Clips from @streamera.clips go to" });
  await expect(preview.getByText("Streamer A TikTok")).toBeVisible();
  await expect(preview.getByText("Streamer A YouTube")).toBeVisible();
  await expect(preview.getByText("Streamer B TikTok")).toHaveCount(0);

  // disable one route from the side panel
  await page.locator(".funnel-side .filter-btn", { hasText: "@streamera.clips → Streamer A YouTube" }).click();
  await page.getByRole("switch", { name: "Route enabled" }).click();
  await expect(page.locator(".funnel-side .filter-btn", { hasText: "Streamer A YouTube" }).getByText("off")).toBeVisible();

  await page.reload();
  await expect(page.locator(".react-flow__edge")).toHaveCount(3);

  // --- settings persist
  await page.getByRole("navigation").getByRole("link", { name: "Settings" }).click();
  await page.getByRole("tab", { name: "AI, costs & processing" }).click();
  await page.getByLabel("Monthly budget (USD)").fill("42");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Settings saved")).toBeVisible();
  await page.reload();
  await page.getByRole("tab", { name: "AI, costs & processing" }).click();
  await expect(page.getByLabel("Monthly budget (USD)")).toHaveValue("42");
  await page.getByRole("tab", { name: "Security & data" }).click();
  await expect(page.getByText("route.auto_created")).toBeVisible();

  // --- dashboard reflects real data
  await page.keyboard.press("Control+1");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  const routes = page.locator(".stat", { hasText: "Active routes" });
  await expect(routes.locator(".value")).toHaveText("2");
  await expect(page.locator(".stat", { hasText: "Published clips" }).locator(".value")).toHaveText("—");
});

test("unbuilt modules say so instead of faking it", async ({ page }) => {
  await page.goto("/editor");
  await expect(page.getByText("Not started · Milestone 3")).toBeVisible();
  await expect(page.locator(".main button")).toHaveCount(0);
});

test("the API refuses requests without the window token", async ({ request }) => {
  const r = await request.get("/api/sources");
  expect(r.status()).toBe(401);
});
