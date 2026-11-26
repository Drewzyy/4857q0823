// YouTube Studio's upload box: the video, the title and description, not made for kids, Public, then Publish.
Vyral.run(async (job, cfg) => {
  const input = await Vyral.waitFor(() => document.querySelector('input[type="file"][name="Filedata"], ytcp-uploads-file-picker input[type="file"]'),
    90000, "the upload box");
  Vyral.putFile(input, await Vyral.video(job));
  const title = await Vyral.waitFor(() => document.querySelector("#title-textarea #textbox"), 120000, "the title box");
  await Vyral.sleep(1500); // Studio fills in the file name first: replaced below
  Vyral.type(title, (job.title || "").slice(0, 100));
  const desc = document.querySelector("#description-textarea #textbox");
  if (desc) Vyral.type(desc, job.caption || "");
  (await Vyral.waitFor(() => document.querySelector('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]'), 30000, "the made-for-kids choice")).click();
  for (let i = 0; i < 3; i++) { // details, video elements, checks
    const next = await Vyral.waitFor(() => {
      const b = document.querySelector("#next-button");
      return b && b.getAttribute("aria-disabled") !== "true" ? b : null;
    }, 120000, "the Next button");
    next.click();
    await Vyral.sleep(1500);
  }
  (await Vyral.waitFor(() => document.querySelector('tp-yt-paper-radio-button[name="PUBLIC"]'), 30000, "the Public choice")).click();
  const link = document.querySelector('ytcp-video-info a[href*="youtu"], a.ytcp-video-info[href*="youtu"]')?.href || null;
  const done = await Vyral.waitFor(() => {
    const b = document.querySelector("#done-button");
    return b && b.getAttribute("aria-disabled") !== "true" ? b : null;
  }, 15 * 60000, "the Publish button");
  await Vyral.press(done, job, "filled in. Check it, then press Publish.");
  await Vyral.waitFor(() => /video published|processing will begin|uploaded/i.test(document.body.innerText)
    || !document.querySelector("ytcp-uploads-dialog[opened], #done-button"), 20 * 60000, "the video to publish");
  const id = link && (link.match(/youtu\.be\/([\w-]{6,})/) || link.match(/[?&]v=([\w-]{6,})/) || link.match(/shorts\/([\w-]{6,})/));
  return id ? `https://www.youtube.com/shorts/${id[1]}` : null;
});
