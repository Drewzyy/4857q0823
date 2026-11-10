# External services

Vyral doesn't log into or publish to any platform. You download each clip and upload it yourself, so no app
reviews or developer accounts are needed. Everything below is free.

| Service | Used for | How |
|---|---|---|
| TikTok, YouTube | Reading a post you hand Vyral (pasted, copied, or sent through the Discord inbox), its caption and audio; listing a watched account's newest posts | yt-dlp with browser impersonation (curl_cffi). Public pages only, no login. TikTok often refuses account listings, so copied links and the Discord inbox are the dependable way in. |
| Twitch, YouTube, Kick | Listing a streamer's recent broadcasts and their top clips, downloading the audio to find a moment, and downloading the matched section in full quality | yt-dlp, public data, no login. Broadcasts that are still live are skipped until they end. |
| Discord | Notifications (webhook you paste) and the phone inbox (a bot you create; Vyral reads one channel) | Discord HTTP API. The webhook URL and bot token are kept in the OS keychain. |
| GitHub (Drewzyy/vyral-releases) | App updates | Signed update files and latest.json, checked hourly. |
| Hugging Face | One-time download of the speech model for captions | faster-whisper models, cached in the app's data folder. |

Analytics read the public view, like, comment and share counts of posts you link (TikTok and YouTube) with yt-dlp;
Instagram and Facebook numbers are typed in.
