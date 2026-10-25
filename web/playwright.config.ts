// The end-to-end flow test (Implementation Plan D8.6, TRD §14): one server like production (the API
// serving the built web app from one origin) with its own data folder and the recorded model replies,
// so it never calls Token Factory. Build first: `pnpm e2e` builds and runs it.
import os from "node:os";
import path from "node:path";
import { defineConfig } from "@playwright/test";

const PORT = 8010;
const root = path.resolve(import.meta.dirname, "..");
const data = path.join(os.tmpdir(), "sherlock-e2e");

export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    acceptDownloads: true,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: `uv run --directory "${path.join(root, "api")}" python tests/e2e_server.py --port ${PORT}`,
    url: `http://localhost:${PORT}/healthz`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      DATA_DIR: data,
      DATABASE_URL: `sqlite:///${path.join(data, "sherlock.db").replaceAll("\\", "/")}`,
      LLM_MOCK: path.join(root, "api", "tests", "fixtures", "llm"),
      WEB_DIST_DIR: path.join(root, "web", "dist"),
      JOB_WORKERS: "4",
      PURGE_INTERVAL_S: "0",
    },
  },
});
