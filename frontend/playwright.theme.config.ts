import { defineConfig, devices } from "@playwright/test";

/**
 * Rendering assertions that defend a feature, against a real build of the app.
 *
 * Separate from playwright.probe.config.ts, which must NOT start a server (it
 * measures whether a browser runs at all). Separate from playwright.config.ts,
 * whose tests/e2e suite has been red since June because it starts no backend —
 * a result buried in a red suite proves nothing.
 *
 * These specs hit `/` only, which is static, so no backend is required.
 */
export default defineConfig({
  testDir: "./tests/rendering",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: "list",
  timeout: 60_000,
  use: { baseURL: "http://127.0.0.1:3000", ...devices["Desktop Chrome"] },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "pnpm build && pnpm exec next start -H 127.0.0.1 -p 3000",
    url: "http://127.0.0.1:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: {
      SKIP_ENV_VALIDATION: "1",
      OMNI_HARNESS_AUTH_DISABLED: "1",
      // Workflows render on Automations only behind this build-time flag.
      NEXT_PUBLIC_FEATURE_WORKFLOWS: "true",
    },
  },
});
