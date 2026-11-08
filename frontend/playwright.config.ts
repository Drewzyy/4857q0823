import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Each run gets a fresh, throwaway data directory so tests never touch real data.
const dataDir = process.env.CLIPPR_E2E_DATA ?? mkdtempSync(join(tmpdir(), "clippr-e2e-"));
const port = 8799;

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  use: { baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1440, height: 900 }, trace: "off" },
  webServer: {
    command: `python3 -m clippr --port ${port} --data-dir ${dataDir} --frontend ../frontend/dist`,
    cwd: "../backend",
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    env: { CLIPPR_SECRET_BACKEND: "file" },
  },
});
