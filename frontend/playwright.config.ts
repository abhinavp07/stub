import { defineConfig, devices } from "@playwright/test";

// The e2e run gets its own API, web server and database so it never touches dev data.
const API_PORT = 8100;
const WEB_PORT = 3100;
const DATABASE_URL =
  process.env.E2E_DATABASE_URL ??
  "postgresql+asyncpg://receipts:receipts@localhost:5432/receipts_e2e";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: [
        "uv run python -m scripts.ensure_database",
        "uv run alembic upgrade head",
        `uv run uvicorn app.main:app --port ${API_PORT}`,
      ].join(" && "),
      cwd: "../backend",
      url: `http://localhost:${API_PORT}/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        DATABASE_URL,
        JWT_SECRET: "e2e-only-secret-that-is-at-least-32-bytes-long",
        TEXTRACT_MODE: "mock",
        STORAGE_MODE: "local",
        LOCAL_UPLOAD_DIR: "./.uploads-e2e",
        MOCK_TEXTRACT_DELAY_SECONDS: "1",
        RATE_LIMIT_ENABLED: "false", // repeated local runs would hit the signup-per-IP limit
        CORS_ORIGINS: `http://localhost:${WEB_PORT}`,
      },
    },
    {
      command: `pnpm exec next dev --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}/login`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: { API_BASE_URL: `http://localhost:${API_PORT}`, NEXT_TELEMETRY_DISABLED: "1" },
    },
  ],
});
