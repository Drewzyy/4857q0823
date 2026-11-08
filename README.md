# Vyral

Vyral watches clipping accounts on TikTok and YouTube Shorts. When one posts, Vyral finds that exact moment in the streamer's full stream, cuts it in full quality, frames it vertically over a blurred background, writes a caption for each of your pages, and pings your Discord. You download the video and upload it yourself, so there are no platform audits or API approvals involved.

## Install (no Terminal needed)

Go to this repo's **Releases** page and download the file for your computer from **Assets**:

- **Mac (Apple Silicon: M1 to M4):** `Vyral-Mac-AppleSilicon.dmg`. Open it and drag Vyral to Applications. The first time, macOS says it can't verify the developer: open **System Settings > Privacy & Security**, scroll down, click **Open Anyway**.
- **Windows 10/11:** `Vyral-Windows-Setup.exe`. Run it. If you see "Windows protected your PC", click **More info > Run anyway**.

Those warnings show up because the app isn't signed with a paid Apple Developer ($99/year) or Windows code-signing certificate. Signing removes them; ask if you want to set that up.

Vyral starts automatically when your computer starts and lives in the menu bar (Mac) or system tray (Windows). Closing the window doesn't stop it. To stop monitoring, use **Quit Vyral** from that icon.

## Setup (about 5 minutes)

1. **Source Accounts > New creator:** the streamer's name, their Twitch or YouTube channel link, and tick that you have permission to clip them.
2. **Source Accounts > Add account:** the clipping accounts to watch (handle or link), assigned to that creator.
3. **Destinations > Add destination:** each page you post to, with its handle.
4. **Account Funnel:** drag each source onto the pages it should feed, or click **Auto-route by creator**.
5. **Settings > Notifications:** paste a Discord webhook (optional).

The first check of a new source account only records what it already posted. From then on, every new post becomes a clip.

## What happens when a source posts

1. Discord: "@account just posted a new video."
2. Vyral listens to the post and searches the creator's latest streams (4 by default) for the same audio. It handles jump cuts and music added on top. If it can't find the moment with confidence it says so instead of guessing, and you can paste the exact stream link to retry.
3. It downloads only that part of the stream in the best quality available and renders it per destination format (1080x1920, up to 60 fps by default).
4. **Ready to Upload** shows the clip with a caption per page: the post's title without their hashtags and @mentions, your extra caption, the creator credit and your hashtags. YouTube gets a separate title and #shorts.
5. Discord: "Clip ready for upload" with every page and platform it's for.
6. You click **Save to computer** (full quality, into Downloads > Vyral), upload, and click **Mark uploaded**.

Clips and cached stream data are deleted automatically after 30 days (changeable in Settings). Files you saved to your computer are never touched.

## Limits to know about

- **TikTok has no official way to watch accounts you don't own.** Vyral reads their public profile page the same way a browser would, with no login, checking every 10 minutes with backoff. TikTok's terms don't allow automated access, and TikTok changes its site often, so checks can stop working until Vyral gets an update. If that happens the Source Accounts page shows the error, and you can still paste a post link on the Activity page.
- **Instagram and Twitch accounts can't be watched** as sources (Instagram requires a login). Twitch and YouTube work as stream sources.
- **Only Apple Silicon Macs** are built right now. Intel Mac builds can be added.
- **No captions are burned into the video yet.** The word-by-word orange/white captions are part of the Video Editor, which is next.

## For developers

[DEVELOPMENT](DEVELOPMENT.md) · [ARCHITECTURE](ARCHITECTURE.md) · [ROADMAP](ROADMAP.md) · [TESTING](TESTING.md) · [SECURITY](SECURITY.md) · [API_INTEGRATIONS](API_INTEGRATIONS.md) · [COSTS](COSTS.md) · [CHANGELOG](CHANGELOG.md)
