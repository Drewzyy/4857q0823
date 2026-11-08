# Changelog

## 0.2.0: Vyral

- Renamed to Vyral.
- Automatic pipeline: watches TikTok and YouTube Shorts source accounts, finds each new post's moment in the creator's recent streams by audio matching, downloads that section in full quality, renders per destination format, writes captions.
- Ready to Upload page: preview, per-page title/caption with copy buttons, Save to computer (full quality into Downloads/Vyral), Mark uploaded.
- Activity page: every new post and what happened to it, retry with a specific stream link, make a clip from a pasted link.
- Discord webhook notifications for new posts, ready clips and problems, with a test button.
- Destinations no longer need platform logins: editable name and handle. API publishing removed from the UI (no audits needed).
- Clips and cached stream data auto-delete after 30 days.
- Mac (.dmg) and Windows (setup .exe) installers built by GitHub Actions. Starts at login, keeps monitoring from the menu bar / tray.
- 41 backend tests including the full pipeline with real audio matching and rendering; 5 browser tests.

## 0.1.0: foundation

Local backend, accounts, funnel, dashboard, settings, job queue, desktop shell.
