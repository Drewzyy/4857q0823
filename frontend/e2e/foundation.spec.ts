import { expect, test, type Page } from "@playwright/test";

const nav = (page: Page, name: string) => page.getByRole("navigation").getByRole("link", { name }).click();

async function dragRoute(page: Page, from: string, to: string) {
  const handle = page.locator(".react-flow__node", { hasText: from }).locator(".react-flow__handle-right");
  const target = page.locator(".react-flow__node", { hasText: to }).locator(".react-flow__handle-left");
  const a = (await handle.boundingBox())!;
  const b = (await target.boundingBox())!;
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 15 });
  await page.mouse.up();
}

test("a clip made automatically is ready to upload with captions per page", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".brand")).toHaveText("Vyral");
  await expect(page.locator(".stat", { hasText: "Ready to upload" }).locator(".value")).toHaveText("2");
  await expect(page.getByRole("navigation").getByRole("link", { name: /Ready to Upload/ })).toContainText("2");

  await nav(page, "Activity");
  await expect(page.getByText("Clip ready", { exact: true })).toBeVisible();
  await expect(page.getByText("@streamera.clips")).toBeVisible();

  await nav(page, "Ready to Upload");
  const card = page.locator(".card", { hasText: "He did NOT just say that" }).first();
  await expect(card.getByText(/Cut from/)).toBeVisible();
  await expect(card.getByText(/Deletes in 30 days/)).toBeVisible();

  // The preview plays the real rendered file.
  const video = card.locator("video");
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState >= 1 && v.duration > 10)).toBe(true);
  expect(await video.evaluate((v: HTMLVideoElement) => v.videoHeight)).toBe(1920);

  // TikTok tab: post text, streamer + stream date, original hashtags + page hashtags + #vyralclips.
  await card.getByRole("tab", { name: /Streamer A TikTok/ }).click();
  const caption = card.getByLabel("Caption");
  await expect(caption).toHaveValue(/^He did NOT just say that\n\nStreamer: Streamer A\nStreamed Nov [78], 2026\n\n#fyp #gaming #vyralclips$/);
  await expect(card.getByText(/Streamed Nov [78], 2026/).first()).toBeVisible();
  await card.getByRole("button", { name: "Save to computer" }).click();
  await expect(page.getByText(/Saved to .*Downloads.Vyral.*Streamer A TikTok - He did NOT just say that\.mp4/)).toBeVisible();

  // Edit the caption, it sticks.
  await caption.fill("my own caption #gaming");
  await caption.blur();
  await page.reload();
  await page.locator(".card", { hasText: "He did NOT just say that" }).first().getByRole("tab", { name: /Streamer A TikTok/ }).click();
  await expect(page.getByLabel("Caption")).toHaveValue("my own caption #gaming");

  // YouTube tab has a separate title and #shorts.
  await page.getByRole("tab", { name: /Streamer A YouTube/ }).click();
  await expect(page.getByLabel("Title")).toHaveValue("He did NOT just say that");
  await expect(page.getByLabel("Description")).toHaveValue(/#fyp #vyralclips #shorts$/);

  // Mark TikTok uploaded -> it moves to the Uploaded tab, YouTube stays Ready.
  await page.getByRole("tab", { name: /Streamer A TikTok/ }).click();
  await page.getByRole("button", { name: "Mark uploaded" }).click();
  await expect(page.getByText("Marked as uploaded")).toBeVisible();
  await expect(page.getByRole("tab", { name: /Streamer A TikTok/ })).toHaveCount(0);
  await page.getByRole("tab", { name: "Uploaded" }).click();
  await expect(page.getByRole("tab", { name: /Streamer A TikTok/ })).toBeVisible();
});

test("destinations are just names and handles you can edit", async ({ page }) => {
  await page.goto("/destinations");
  const card = page.locator(".card", { hasText: "Streamer A TikTok" });
  await expect(card.getByText("@streamera.tt")).toBeVisible();
  await card.getByRole("button", { name: "Rename Streamer A TikTok" }).click();
  await page.getByLabel("Destination name").fill("Main TikTok");
  await page.getByLabel("Destination handle").fill("https://www.tiktok.com/@main.page");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Main TikTok")).toBeVisible();
  await expect(page.getByText("@main.page")).toBeVisible();

  await page.getByRole("button", { name: "Add destination" }).first().click();
  await page.getByLabel("Platform").selectOption({ label: "Instagram" });
  await page.getByLabel("Name", { exact: true }).fill("Streamer B Insta");
  await page.getByLabel("Handle", { exact: true }).fill("@b.insta");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.reload();
  await expect(page.getByText("Streamer B Insta")).toBeVisible();
  await expect(page.getByText("Main TikTok")).toBeVisible();
  await expect(page.getByRole("button", { name: /Connect/ })).toHaveCount(0);
});

test("creators carry their stream channels and permission, sources show watch status", async ({ page }) => {
  await page.goto("/sources");
  await expect(page.getByRole("button", { name: "Check @streamera.clips now" })).toBeVisible();
  await page.getByRole("button", { name: "New creator" }).click();
  await page.getByLabel("Streamer / creator name").fill("Streamer B");
  await page.getByLabel(/Where their full streams are/).fill("https://evil.example/x");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/evil.example/)).toBeVisible();
  await page.getByLabel(/Where their full streams are/).fill("twitch.tv/streamerb");
  await page.getByLabel(/I have permission to clip/).check();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".filter-btn", { hasText: "Streamer B" })).toBeVisible();

  await page.getByRole("button", { name: "Add account" }).first().click();
  await page.getByLabel("Username or profile link").fill("@streamerb.clips");
  await page.getByRole("button", { name: "Creator", exact: true }).click();
  await page.getByRole("checkbox", { name: "Streamer B" }).check();
  await page.getByRole("checkbox", { name: "Streamer A" }).check();  // one account clipping two streamers
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check @streamerb.clips now" })).toBeVisible();
  const picker = page.getByRole("button", { name: "Creators for @streamerb.clips" });
  await expect(picker).toContainText("Streamer A");
  await expect(picker).toContainText("Streamer B");

  // Funnel: dragging B's source onto A's page asks first.
  await nav(page, "Account Funnel");
  // It clips Streamer A too, so routing it to A's page is allowed without the mix warning.
  await dragRoute(page, "@streamerb.clips", "Streamer A YouTube");
  await expect(page.getByRole("heading", { name: "Mix creators?" })).toHaveCount(0);
});

test("discord and storage settings", async ({ page }) => {
  await page.goto("/settings?tab=notifications");
  await page.getByLabel("Discord webhook URL").fill("https://example.com/not-a-webhook");
  await page.getByRole("button", { name: "Save & test" }).click();
  await expect(page.getByText(/isn't a Discord webhook link/)).toBeVisible();
  await page.getByRole("switch", { name: "A source account posts a new video" }).click();
  await page.reload();
  await expect(page.getByRole("switch", { name: "A source account posts a new video" })).not.toBeChecked();

  await page.getByRole("tab", { name: "Monitoring & storage" }).click();
  await page.getByLabel("Accuracy").selectOption("best");
  await page.getByLabel("Language spoken on stream").selectOption("en");
  await page.getByLabel(/Delete clips after/).fill("14");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Settings saved")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel(/Delete clips after 14 days/)).toBeVisible();
  await expect(page.getByLabel("Accuracy")).toHaveValue("best");
  await expect(page.getByLabel("Language spoken on stream")).toHaveValue("en");
});

test("the API refuses requests without the window token", async ({ request }) => {
  expect((await request.get("/api/sources")).status()).toBe(401);
  expect((await request.get("/api/media/outputs/1")).status()).toBe(401);
});

test("edit the text burned into a clip and re-render it", async ({ page }) => {
  await page.goto("/ready");
  const card = page.locator(".card", { hasText: "He did NOT just say that" }).first();
  await card.getByRole("tab", { name: /Streamer A YouTube/ }).click();
  const video = card.locator("video");
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState >= 1)).toBe(true);
  const before = await video.getAttribute("src");

  await card.getByRole("button", { name: /Edit text on video/ }).click();
  await expect(card.getByLabel("Title on the video")).toHaveValue("He did NOT just say that");
  // Defaults: white title, yellow captions, all caps, title shown 5 s.
  await expect(card.getByLabel("Title color", { exact: true })).toHaveValue("#ffffff");
  await expect(card.getByLabel("Captions color", { exact: true })).toHaveValue("#ffe500");
  await expect(card.getByText("Shows for 5 s")).toBeVisible();
  await card.getByLabel("Title on the video").fill("BRO REALLY SAID IT");
  await card.getByRole("button", { name: "Title color #F97316" }).click();
  await card.getByLabel("Size: 88").fill("120");
  await expect(card.locator(".ov-preview .ov-text").first()).toHaveText("BRO REALLY SAID IT");
  await card.getByRole("button", { name: "Re-render with changes" }).click();
  await expect(page.getByText(/Re-rendering\. The new version/)).toBeVisible();
  await expect.poll(async () => card.locator("video").getAttribute("src"), { timeout: 40_000 }).not.toBe(before);
  await expect.poll(() => card.locator("video").evaluate((v: HTMLVideoElement) => v.readyState >= 1 && v.videoHeight === 1920), { timeout: 20_000 }).toBe(true);

  // Fix a caption word: applies to every page (the edit panel stays open after re-rendering).
  await card.getByLabel(/Caption words/).fill("no way he ACTUALLY did that right now");
  await card.getByRole("button", { name: "Save captions" }).click();
  await expect(page.getByText(/Captions updated/)).toBeVisible();
});

test("each page has its own default text style", async ({ page }) => {
  await page.goto("/destinations");
  await page.locator(".card", { hasText: "Streamer A YouTube" }).getByRole("button", { name: /Text, caption & format/ }).click();
  await page.getByLabel("Captions color", { exact: true }).fill("#38bdf8");
  await page.getByLabel("Position: 70% from top").fill("80");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved")).toBeVisible();
  await page.reload();
  await page.locator(".card", { hasText: "Streamer A YouTube" }).getByRole("button", { name: /Text, caption & format/ }).click();
  await expect(page.getByLabel("Captions color", { exact: true })).toHaveValue("#38bdf8");
  await expect(page.getByLabel("Position: 80% from top")).toBeVisible();
});

test("post links feed the analytics page", async ({ page }) => {
  await page.goto("/ready");
  const card = page.locator(".card", { hasText: "He did NOT just say that" }).first();
  await card.getByRole("tab", { name: /Streamer A YouTube/ }).click();
  await card.getByLabel(/Link to your post/).fill("https://www.tiktok.com/@x/video/1");
  await card.getByRole("button", { name: "Save link" }).click();
  await expect(page.getByText(/isn't a Youtube link/)).toBeVisible();
  await card.getByLabel(/Link to your post/).fill("https://youtube.com/shorts/abc123");
  await card.getByRole("button", { name: "Save link" }).click();
  await expect(page.getByText(/Vyral will read its views/)).toBeVisible();
  await page.getByRole("navigation").getByRole("link", { name: "Analytics" }).click();
  await expect(page.getByRole("heading", { name: "Analytics" })).toBeVisible();
  await expect(page.locator(".stat", { hasText: "Clips" }).locator(".value")).not.toHaveText("0");
  await expect(page.getByText(/uploads have numbers/)).toBeVisible();
  await page.getByRole("button", { name: "All time" }).click();
  await expect(page.getByRole("heading", { name: "By platform" })).toBeVisible();
});
