# Working on Vyral

Follow AGENTS.md: write the smallest complete change, reuse what is already here, and never cut validation,
error handling, security or the tests that guard risky logic.

Project specifics:
- Backend: backend/ (Python, FastAPI). Tests: `cd backend && python -m pytest -q`. Lint: `python -m pyflakes clippr`.
- App: frontend/ (React, TypeScript). Check: `npx tsc --noEmit -p .`; browser tests: `npx playwright test`.
- Database changes go in backend/clippr/migrations/versions/ as a new numbered migration; never edit a released one.
- Releases build on push (Mac and Windows installers, with a self-test). Users get them through auto-update.
