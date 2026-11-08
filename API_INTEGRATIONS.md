# Platform integrations

**Since 0.2.0 Vyral does not publish through platform APIs.** You download each clip and upload it yourself, which avoids TikTok's and Google's app audits entirely. The OAuth connectors below are still in the code (tested) for a future optional auto-publish, but nothing in the app uses them.

## What Vyral reads instead

- **Source accounts (TikTok, YouTube Shorts):** public profile pages via yt-dlp, no login or cookies, every 10 minutes per account with jitter and exponential backoff (up to 6 hours) when blocked. Not an official API: TikTok's terms prohibit automated access and its site changes often, so this can break until yt-dlp (bundled) is updated in a new Vyral build.
- **Streams (Twitch past broadcasts, YouTube live streams/videos):** listing and downloading via yt-dlp. Only the matched section is downloaded in full quality; for matching, the stream's audio is downloaded once, reduced to ~20 MB of features per 10 hours, and the audio deleted. Vyral only processes creators you've confirmed you have permission to clip.
- **Discord:** incoming webhooks (validated to discord.com webhook URLs, retries on rate limits, `allowed_mentions` disabled so a post title can't ping @everyone).

---


What each platform actually allows, what's built, and what needs you. Verified against official docs in November 2026; recheck when something fails.

## Why there's a one-time setup per platform

TikTok, Google and Meta only accept login requests from apps registered in a developer account, and none of them offer an API to register one. So someone has to register AI Clipper once per platform. That's you, since this is your copy. The in-app wizard reduces it to: open link, create app, copy one redirect address, paste two keys (or drop a file for Google). Keys are verified live before being saved.

To remove the step for other users of a build, ship `backend/clippr/platform_apps.json`:

```json
{ "youtube": {"client_id": "...", "client_secret": "..."}, "tiktok": {"client_id": "...", "client_secret": "..."}, "meta": {"client_id": "...", "client_secret": "..."} }
```

Note that anything shipped in an app binary can be extracted. Google treats desktop client secrets as non-confidential by design, but for TikTok and Meta a hosted token-exchange service would be the proper fix if this is ever distributed widely.

A paid aggregator (Ayrshare, Upload-Post and similar) could replace all three registrations with a single hosted login. Not used, since it costs money and routes your tokens through a third party. Ask if you want it as an adapter.

## YouTube (Google)

- Flow: OAuth 2.0 for installed apps, loopback redirect `http://127.0.0.1:<port>/oauth/callback/youtube`, PKCE S256. Desktop clients need no redirect registration.
- Scopes: `youtube.upload`, `youtube.readonly`.
- Limits you will hit:
  - Consent screen in **Testing**: refresh tokens expire after 7 days. Publishing the consent screen (fine for a single-user personal tool) removes that. Google may show an "unverified app" warning you click through.
  - Uploads from unverified API projects are locked to **private** until the project passes Google's API audit. Default destination visibility is private for that reason.
  - Data API quota: 10,000 units/day by default, and uploads are the most expensive call. The publisher will read the current cost from Google's quota table rather than hardcode it.
- Status: connect, refresh, revoke built and mock-tested. Upload: Milestone 6.

## TikTok

- Flow: Login Kit for Desktop. Redirect must be localhost/127.0.0.1 with a port; wildcard port allowed, so register `http://127.0.0.1:*/oauth/callback/tiktok/`. PKCE with a **hex** SHA-256 challenge (TikTok-specific).
- Scopes: source accounts request `user.info.basic, user.info.profile, user.info.stats, video.list`; destinations also `video.upload, video.publish`.
- Limits:
  - Unaudited apps: Direct Post is forced to `SELF_ONLY` (private), the posting account must be private, and at most 5 users can post per 24h. Passing TikTok's audit lifts this.
  - No API exposes **who you follow**. Followed-account sync is not possible legitimately. Supported instead: add by handle/link, CSV, paste list.
  - The Display API only returns videos for accounts that log in. For accounts you don't own, only per-video oEmbed (title, author, thumbnail; no metrics) is available. The Research API has metrics for any public video but is restricted to approved non-profit academic researchers.
- Status: connect (source or destination), refresh, revoke built and mock-tested.

## Facebook + Instagram (Meta)

- Flow: Facebook Login. One login returns every Page you manage and each Page's linked Instagram professional account; all become destinations. Short-lived token is exchanged for a ~60-day token; Page tokens derived from it don't expire.
- Redirect: `http://127.0.0.1:8765/oauth/callback/meta`. In Development mode Meta accepts localhost. If it refuses, host `relay/index.html` on any HTTPS host and paste its URL under Advanced in the setup wizard.
- Scopes: `pages_show_list, pages_read_engagement, pages_manage_posts, instagram_basic, instagram_content_publish, instagram_manage_insights, business_management`.
- Limits:
  - Instagram publishing needs a Business or Creator account linked to a Facebook Page.
  - In Development mode, people with a role on the app (you) get all permissions without App Review. Review is only needed for other users.
  - The ~60-day user token can't be refreshed silently. The app warns a week ahead.
  - Instagram caps API-published posts per account per rolling 24h. The publisher will check `content_publishing_limit` before each post instead of assuming a number.
- Status: connect, long-lived exchange, page discovery, revoke built and mock-tested.

## Twitch (planned, Milestone 5)

Device-code OAuth (no redirect needed). Helix `/videos` lists VOD metadata. Twitch offers no official VOD download API; processing Twitch VODs will require the channel owner's permission and a user-supplied file or a tool you choose to run.

## Browser workspace (planned)

Only for things with no API: opening profiles for you to look at, and capturing reference URLs you choose. It will not log in for you, read cookies, scrape lists, or bypass CAPTCHAs or rate limits.
