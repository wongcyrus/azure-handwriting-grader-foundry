import { defineConfig } from "@playwright/test";
import { FAKE_TOKEN } from "./tests/support";

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  retries: 0,
  outputDir: "../../.local/test-results/browser",
  reporter: [
    ["list"],
    ["junit", { outputFile: "../../.local/test-results/browser.xml" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:18766",
    viewport: { width: 1280, height: 960 },
    channel: "chrome",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chrome-dpr-1", use: { deviceScaleFactor: 1 } },
    { name: "chrome-dpr-2", use: { deviceScaleFactor: 2 } },
  ],
  webServer: [
    {
      command:
        "cd ../.. && uv run --frozen --extra dev --extra engine python -m handwriting_grader_cloud --development --port 18765 --database .local/test-results/canvas.sqlite3",
      url: "http://127.0.0.1:18765/health",
      env: { FOUNDRY_DEV_TOKEN: FAKE_TOKEN },
      reuseExistingServer: false,
      timeout: 120000,
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:18766",
      env: { CANVAS_WEB_PORT: "18766", CANVAS_API_PORT: "18765" },
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
});
