import { expect, test } from "@playwright/test";

const POST = `💰 LACY GTA VI Marathon Pool Campaign
Clip and create content from approved footage to earn money based on your views!
📌 Campaign Information
* Creator: Lacy
* Content Type: Social media clipping
* Eligible Platforms: Tiktok, Instagram, YouTube, X
🎬 Approved Footage
Content must be sourced from any stream, video or clip featuring Lacy during his GTA marathon, beginning November 18th, 2026.
$12,500 LACY GTA VI Marathon Pool Campaign
Min Views (MVR)
750,000
Audience
English Speaking
[Join Campaign](https://contentrewards.com/c/campaigns/a5c63fad-cd53-4b81-9305-4a2d1696872a?src=share)[Join Discord](https://discord.com/invite/reachclipping)
[Requirements](https://reachclipping.com/LACYGTA#requirements)
* Your caption/text overlay must mention LACY's name
* Your captions must use the hashtag: #LACY
3. Submit Your Video Links
Once verified, head back to Content Rewards and paste the link to every LACY clip you've posted. Submit within 30 minutes of posting.`;

test("add a campaign from its pasted post, find it by tag, then delete it", async ({ page }) => {
  await page.goto("/campaigns");
  await expect(page.getByText("No campaigns yet")).toBeVisible();
  await page.getByRole("button", { name: "Add campaign" }).first().click();
  const box = page.getByRole("dialog");
  await box.getByLabel("Paste the campaign post").fill(POST);
  await box.getByRole("button", { name: "Fill in from text" }).click();

  await expect(box.getByLabel("Name", { exact: true })).toHaveValue("LACY GTA VI Marathon Pool Campaign");
  await expect(box.getByLabel("Pool")).toHaveValue("$12,500");
  await expect(box.getByLabel("Minimum views")).toHaveValue("750000");
  await expect(box.getByLabel("Footage from")).toHaveValue("2026-11-18");
  await expect(box.getByLabel("Required hashtags")).toHaveValue("#LACY");
  await expect(box.getByLabel("Must mention")).toHaveValue("LACY");
  await expect(box.getByLabel("Submit within (minutes)")).toHaveValue("30");
  for (const p of ["TikTok", "Instagram", "YouTube", "X"]) await expect(box.getByRole("checkbox", { name: p, exact: true })).toBeChecked();
  await expect(page.getByText("Lacy isn't one of your streamers yet. Pick one below.")).toBeVisible();

  const save = box.getByRole("button", { name: "Save" });
  await expect(save).toBeDisabled();  // it needs a tag
  await box.getByLabel("Tag", { exact: true }).fill("lacy-gta");
  await box.getByLabel("Streamer", { exact: true }).selectOption({ label: "Streamer A" });
  await save.click();
  await expect(page.getByText("Campaign added")).toBeVisible();

  const card = page.locator(".card", { hasText: "LACY GTA VI Marathon Pool Campaign" });
  await expect(card).toContainText("0 of 750,000 views");
  await expect(card.getByRole("link", { name: /Join Campaign/ })).toHaveAttribute("href", /^https:\/\/contentrewards\.com\/c\/campaigns\//);
  await expect(card.getByRole("link", { name: /Discord/ })).toHaveAttribute("href", "https://discord.com/invite/reachclipping");

  await page.getByLabel("Search campaigns").fill("LACY-gta");
  await expect(card).toBeVisible();
  await page.getByLabel("Search campaigns").fill("zzz");
  await expect(page.getByText("No campaign matches that")).toBeVisible();
  await page.getByLabel("Search campaigns").fill("lacy-");
  await card.getByRole("button", { name: "Rules and clips" }).click();
  await expect(card.getByText("Captions must use #LACY")).toBeVisible();
  await expect(card.getByText(/None yet/)).toBeVisible();

  // The campaign's requirements can be taken into the streamer's caption rules, on top of rules they already have.
  await page.goto("/sources");
  await page.getByRole("button", { name: "Edit Streamer A" }).click();
  const rules = page.getByRole("dialog");
  await rules.getByLabel("Extra caption line").fill("Follow for daily clips");
  await rules.getByLabel("Copy from a campaign").selectOption({ label: "LACY GTA VI Marathon Pool Campaign (Streamer A)" });
  await expect(rules.getByLabel("Required hashtags")).toHaveValue("#LACY");
  await expect(rules.getByLabel("Must mention")).toHaveValue("LACY");
  await expect(rules.getByLabel("Notes")).toHaveValue(/Must use|mention LACY's name/);
  await rules.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Edit Streamer A" }).click();
  await expect(page.getByRole("dialog").getByLabel("Required hashtags")).toHaveValue("#LACY");
  await expect(page.getByRole("dialog").getByLabel("Extra caption line")).toHaveValue("Follow for daily clips");
  for (const l of ["Required hashtags", "Must mention", "Extra caption line", "Notes"]) await page.getByRole("dialog").getByLabel(l).fill("");  // leave Streamer A as it was
  await page.getByRole("dialog").getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  await page.goto("/campaigns");
  await card.getByRole("button", { name: "Apply rules to Streamer A" }).click();
  await expect(page.getByText("Added to Streamer A's caption rules")).toBeVisible();
  await page.goto("/sources");
  await page.getByRole("button", { name: "Edit Streamer A" }).click();
  await expect(page.getByRole("dialog").getByLabel("Required hashtags")).toHaveValue("#LACY");
  for (const l of ["Required hashtags", "Must mention", "Notes"]) await page.getByRole("dialog").getByLabel(l).fill("");
  await page.getByRole("dialog").getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await page.goto("/campaigns");

  await card.getByRole("button", { name: "Delete LACY GTA VI Marathon Pool Campaign" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByText("No campaigns yet")).toBeVisible();
});
