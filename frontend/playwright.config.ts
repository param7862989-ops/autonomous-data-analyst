import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against the real stack: the production frontend build, the FastAPI backend
 * with PostgreSQL, uploads, the DuckDB sandbox and the LangGraph workflow. Only the language
 * model is scripted (backend/tests/e2e_server.py), so runs are deterministic and free.
 *
 * Requires E2E_DATABASE_URL (a disposable PostgreSQL database) and a prior `npm run build`.
 */
// Not 3000: that is where `docker compose` and `npm run dev` serve the real app, and the tests
// must never attach to it (they would write to its database and call its paid model).
const webPort = Number(process.env.E2E_WEB_PORT ?? 3100);
const webUrl = `http://localhost:${webPort}`;
const databaseUrl = process.env.E2E_DATABASE_URL;
const storageDir = process.env.E2E_STORAGE_DIR ?? "../backend/.e2e-storage";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: webUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "uv run alembic upgrade head && uv run python -m tests.e2e_server --port 8000",
      cwd: "../backend",
      url: "http://localhost:8000/api/health/ready",
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        ...(databaseUrl ? { DATABASE_URL: databaseUrl } : {}),
        STORAGE_DIR: storageDir,
        ENVIRONMENT: "test",
        ALLOWED_ORIGINS: webUrl,
      },
    },
    {
      command: "npm run start",
      url: `${webUrl}/login`,
      timeout: 60_000,
      reuseExistingServer: false,
      env: { PORT: String(webPort), HOSTNAME: "localhost" },
    },
  ],
});
