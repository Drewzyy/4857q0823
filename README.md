# AI Clipper

A local-first macOS app for finding, clipping, editing and publishing short-form video across TikTok, Instagram, YouTube and Facebook, with a learning loop that improves recommendations over time.

This repo is being built milestone by milestone. **Milestone 1 (foundation) is done.** See [ROADMAP.md](ROADMAP.md) for exactly what works today and what doesn't.

## What works now

- Source accounts: add by @handle or profile link (TikTok, YouTube, Twitch, Instagram), bulk paste, CSV import, creators, folders, search, filters, pause/resume, bulk actions.
- Destination accounts: one-click Connect for YouTube, TikTok and Facebook/Instagram through each platform's own login page. One Facebook login brings in every Page you manage plus linked Instagram accounts. Per-destination settings (captions, hashtags, visibility, schedule slots, export format, watermark, title style, approval).
- Account Funnel: drag a source onto a destination to route its clips there. Auto-route by creator. Creator mixing is blocked unless you confirm it. Layout persists.
- Dashboard from real data only. Untracked numbers show as a dash, never as zero.
- Settings: AI budget and model preferences, privacy, processing, storage, connection management, activity log.
- Background service with a persistent job queue that keeps logins fresh while the window is closed.

## Connecting accounts

You click **Connect**, log in on the platform's page, click **Allow**. That's it, once each platform knows the app exists.

The one thing that can't be automated: TikTok, Google and Meta only let *registered* apps request access, and there is no API to register one. So each platform needs a one-time registration in a developer account (free, about 5 minutes each). The app walks you through it with direct links, a copy button for the exact redirect address, and checks your keys with the platform before saving. For YouTube you just drop the downloaded JSON file in. You never touch this again after that.

If you later ship builds to other people, put your registered app IDs in `platform_apps.json` and they skip that step completely. Details in [API_INTEGRATIONS.md](API_INTEGRATIONS.md).

## Run it

```bash
# backend + UI on http://127.0.0.1:8765
cd frontend && npm install && npm run build
cd ../backend && pip install -e ".[dev]" && python -m clippr
```

Build the Mac app (on a Mac): `./scripts/build-mac-app.sh`. Output lands in `desktop/src-tauri/target/release/bundle/`.

More in [DEVELOPMENT.md](DEVELOPMENT.md). Tests: [TESTING.md](TESTING.md).

## Docs

[ARCHITECTURE](ARCHITECTURE.md) · [ROADMAP](ROADMAP.md) · [API_INTEGRATIONS](API_INTEGRATIONS.md) · [SECURITY](SECURITY.md) · [COSTS](COSTS.md) · [DEVELOPMENT](DEVELOPMENT.md) · [TESTING](TESTING.md) · [CHANGELOG](CHANGELOG.md)

## Content rights

Following or adding an account does not grant permission to reuse its videos. The app is built around footage you own or are licensed to use, and official platform APIs. It does not scrape, bypass logins, CAPTCHAs or rate limits, or read browser cookies or passwords.
