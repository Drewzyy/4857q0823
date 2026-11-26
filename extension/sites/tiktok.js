// TikTok Studio's upload page: the video, the caption, then Post (pressed by you, or by Auto-post).
Vyral.run(async (job, cfg) => {
  const input = await Vyral.waitFor(() => document.querySelector('input[type="file"][accept*="video"]'), 90000, "the upload box");
  Vyral.putFile(input, await Vyral.video(job));
  const editor = await Vyral.waitFor(() => document.querySelector(
    '[data-e2e="caption_container"] [contenteditable="true"], .public-DraftEditor-content[contenteditable="true"], div[contenteditable="true"]'),
  120000, "the caption box");
  await Vyral.sleep(1500); // TikTok fills in the file name first: replaced below
  Vyral.type(editor, job.caption);
  document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); // close hashtag suggestions
  const post = await Vyral.waitFor(() => {
    const b = document.querySelector('button[data-e2e="post_video_button"]') || Vyral.byText(/^post$/i, "button");
    return b && !b.disabled && b.getAttribute("aria-disabled") !== "true" ? b : null;
  }, 15 * 60000, "the video to finish uploading");
  await Vyral.press(post, job, "filled in. Check it, then press Post.", () => { const b = document.querySelector('button[data-e2e="post_video_button"]') || Vyral.byText(/^post$/i, "button"); return b && !b.disabled ? b : null; });
  await Vyral.waitFor(() => /manage your posts|your video (has been|is being) (uploaded|posted)|video published|posted/i.test(document.body.innerText)
    || /\/tiktokstudio\/content/.test(location.pathname), 20 * 60000, "the post to go out");
  return null; // TikTok doesn't show the link here: Vyral finds it on your page
});
