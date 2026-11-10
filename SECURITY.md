# Security

No app is unhackable. This is what's in place, what's planned, and what's out of scope.

## In place (Milestone 1)

- **Network exposure.** The backend binds to 127.0.0.1 only. Every `/api/*` call must carry a random per-launch token that's only delivered inside the app's own HTML. Requests with a `Host` other than localhost are refused (DNS-rebinding defence). State-changing requests with a foreign `Origin` are refused (CSRF). No CORS is enabled.
- **Credentials.** The Discord webhook URL and bot token live in the OS keychain, never in SQLite, logs or the UI (only a short hint is shown). Off-Mac (CI, Linux) they go in an AES (Fernet) encrypted file with a 0600 key file; weaker, and the UI says which one is active. Both are write-only from the UI.
- **No password handling.** Logins happen on the platform's own page in your normal browser. The app never sees passwords and never reads browser cookies.
- **Input validation.** Pydantic models with length limits and `extra="forbid"` on all settings blobs. Usernames and URLs are parsed against allowlisted hosts. CSV imports are size- and row-capped. SQL only through SQLAlchemy parameter binding.
- **Webview isolation.** The Tauri window loads the UI from the local backend with no native IPC permissions. The UI is served with a strict CSP (`script-src 'self'`, `frame-ancestors 'none'`).
- **Logging.** JSON logs with a redaction filter for tokens, secrets, auth codes and Bearer headers. Errors shown to the user never include stack traces.
- **Audit log.** Every account, route, connection and settings change is recorded (no secret values).

## Added in 0.2.0

- Discord webhook stored in the OS credential store; only `discord.com` webhook URLs accepted; mentions disabled in every message.
- Video previews use the same window token (as a query parameter, only on media URLs, because `<video>` can't send headers).
- Stream links restricted to Twitch/YouTube formats; post links to TikTok/YouTube.
- Downloaded media is only ever passed to FFmpeg as data, never executed. Temporary files are cleaned up after each clip and on a 6-hour timer.
- The background service exits within seconds if the app process disappears, so a crash never leaves a hidden second copy running.

## Planned

- Media processing (Milestone 2): FFmpeg in a subprocess with timeouts and resource limits, type detection by probing content not extensions, size caps, no network for the child process; macOS sandbox profile for the sidecar.
- SSRF guard for any URL the app fetches on your behalf (oEmbed etc.): https only, allowlisted hosts, no private IP ranges, no redirects off-allowlist.
- `pip-audit` and `npm audit` in CI (workflow included, runs on push).
- Encrypted backups of the database, signed and notarized builds, signed auto-updates.

## Out of scope by design

Bypassing logins, CAPTCHAs, rate limits or platform restrictions; extracting browser passwords or cookies; downloading content you don't have rights to.

## Reporting

Open a private security advisory on the GitHub repo.
