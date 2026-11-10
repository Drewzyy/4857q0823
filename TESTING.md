# Testing

```bash
cd backend && python -m pytest -q            # 41 tests, ~45s (renders real video)
cd frontend && npm run build && npx playwright test   # 5 E2E tests; the test server first makes a real clip through the real pipeline
```

## What's covered

- **Backend unit/integration:** URL parsing (valid and hostile input), API auth token, DNS-rebinding Host check, cross-origin write block, log redaction, CRUD for creators/folders/sources/destinations, CSV and paste import with duplicates and bad rows, settings validation and deep merge, funnel rules (duplicates, cross-creator confirmation, auto-route, resolve excludes disabled and mismatched routes, cascade on delete, layout persistence), dashboard counts, job queue (retry with backoff, permanent failure, idempotency, cancel, crash recovery).
- **E2E (Playwright, real UI + backend):** create creators, add source by URL with platform detection, invalid input error, bulk import with duplicate/invalid reporting, monitoring toggle + filter, planned destinations, destination settings persist across reload, guided setup opens with the exact redirect, drag-and-drop route in the funnel, cross-creator confirmation, auto-route, routing preview, disable route, persistence across reload, settings persistence, audit log, dashboard reflects real counts, unbuilt modules show no controls, API rejects calls without token.
- **Packaging:** PyInstaller sidecar built and run; migrations applied, UI served. Tauri shell compiles (`cargo check`).

- **Pipeline (tests/test_pipeline.py):** baseline on first check, new post -> Discord ping -> match in the right stream (wrong stream skipped) at the right second -> keyframe-offset section re-aligned -> two renders for two formats -> captions per platform -> ready ping naming both platforms -> preview auth -> save to Downloads -> edit + mark uploaded -> stream features cached -> 30-day expiry deletes files. Plus missing permission, no match, check failures with backoff, unsupported platforms, monitoring off, bad stream links, bad webhooks.
- **Installers (CI):** each OS builds the service, starts it and checks it serves the UI with its bundled FFmpeg, builds the installer, then runs the test suite on that OS.

## Not covered yet (needs you or a Mac)

- Live logins with real YouTube, TikTok and Meta accounts.
- Keychain backend and the Tauri shell running on macOS.
- Video processing, editor, publishing (later milestones).
