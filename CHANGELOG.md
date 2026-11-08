# Changelog

## 0.3.2

- Fixed: the installed app could hang forever on "Starting background service". The background service now ships as a ready-to-run folder (starts in about a second instead of unpacking ~250 MB every launch), macOS hardened runtime is off (it blocked the service from loading its libraries; it's only needed for paid notarization), and local networking is explicitly allowed.
- The loading screen shows the real reason and recent log lines if the service stops or doesn't respond, and the service output is saved to logs/service-output.log.
- The installer build now installs and launches the real app on Mac and Windows and fails unless the window loads the interface.
- New Vyral logo as the app icon, in the sidebar and as the window icon.

## 0.3.1

- Default title color is white; captions stay bright yellow.
- Caption engine: Accurate speech model by default (Fast / Accurate / Best in Settings, plus language), voice-activity detection so silence and music don't produce invented words, drops segments the model flags as non-speech, collapses repeated-phrase loops, removes known filler phrases, merges stray punctuation, fixes overlapping or zero-length word timings, includes a little audio around the clip so edge words aren't cut.
- Captions sized to fit one line for the chosen font and size, minimum on-screen time, held through short pauses (no flicker), never overlapping.
- Frame rate: keeps the stream's own rate up to 60 fps (59.94 stays 59.94), falls back to 60 instead of 30 when a stream doesn't report it, prefers 1080p60 downloads. Background blur renders much faster with the same look.

## 0.3.0

- Text on the video: title at the top for the first 5 seconds, captions synced to speech. Default ALL CAPS, bold, bright yellow with black outline. Font (4 bundled), size, color, outline, position, title duration and words at a time editable per page and per clip, with a live preview.
- Local speech-to-text (faster-whisper, runs on your computer; model downloads once).
- Fix misheard caption words; word timing is kept. Re-render any clip after editing; the full-quality source cut is kept until the clip expires.
- Captions now keep the post's own hashtags (mentions removed), add #vyralclips, the streamer line and the stream date.
- Fixed: editing endpoints could wait on their own database lock; the job worker could not restart after stopping.

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
