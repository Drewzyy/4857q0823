// Instagram on the web: Create, the video, past the crop and edit steps, the caption, then Share.
Vyral.run(async (job, cfg) => {
  const create = await Vyral.waitFor(() => {
    const icon = document.querySelector('svg[aria-label="New post"], svg[aria-label="Create"]');
    return icon ? icon.closest('a, div[role="button"], span[role="link"], div[role="link"]') || icon : null;
  }, 60000, "the Create button");
  create.click();
  await Vyral.sleep(1500);
  Vyral.byText(/^post$/i, 'a, div[role="button"], span, div[role="menuitem"]')?.click(); // newer menus ask Post or Live
  const input = await Vyral.waitFor(() => document.querySelector('div[role="dialog"] input[type="file"], form input[type="file"]'), 60000, "the upload box");
  Vyral.putFile(input, await Vyral.video(job));
  await Vyral.sleep(2500);
  Vyral.byText(/^ok$/i)?.click(); // "video posts are now shared as reels"
  for (let i = 0; i < 2; i++) { // crop, then edit
    const next = await Vyral.waitFor(() => Vyral.byText(/^next$/i), 120000, "the Next button");
    next.click();
    await Vyral.sleep(2000);
  }
  const caption = await Vyral.waitFor(() => document.querySelector('div[aria-label^="Write a caption"][contenteditable="true"], textarea[aria-label^="Write a caption"]'),
    60000, "the caption box");
  if (caption.tagName === "TEXTAREA") { caption.value = job.caption; caption.dispatchEvent(new Event("input", { bubbles: true })); }
  else Vyral.type(caption, job.caption);
  const share = await Vyral.waitFor(() => Vyral.byText(/^share$/i), 60000, "the Share button");
  await Vyral.press(share, job, "filled in. Check it, then press Share.");
  await Vyral.waitFor(() => /your (reel|post) has been shared|reel shared|post shared/i.test(document.body.innerText), 20 * 60000, "the post to go out");
  return null; // Instagram doesn't show the link here
});
