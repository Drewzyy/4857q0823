import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Each run gets a fresh, throwaway data directory so tests never touch real data.
const dataDir = process.env.CLIPPR_E2E_DATA ?? mkdtempSync(join(tmpdir(), "clippr-e2e-"));
const port = 8799;

export default defineConfig({
  testDir: "e2e",
  timeout: 45_000,
  fullyParallel: false,
  workers: 1,
  use: { baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1440, height: 900 }, trace: "off" },
  webServer: {
    // Seeds one real clip through the real pipeline (local files stand in for TikTok/Twitch).
    command: `python3 tests/e2e_server.py ${port} ${dataDir} ../frontend/dist`,
    cwd: "../backend",
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 240_000,
    env: { CLIPPR_DOWNLOADS_DIR: join(dataDir, "Downloads") },
  },
});
