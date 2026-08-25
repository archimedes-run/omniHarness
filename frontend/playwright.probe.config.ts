import { defineConfig, devices } from "@playwright/test";

/**
 * Config for the browser-capability probe ONLY.
 *
 * Separate from playwright.config.ts because that one starts a Next.js
 * webServer, and the probe must not depend on the application building. The
 * question being measured is "can this environment run a rendering assertion",
 * and a failure to compile the app would answer a different question while
 * looking like an answer to that one.
 *
 * The probe uses page.setContent and needs no server at all.
 */
export default defineConfig({
  testDir: "./tests/probe",
  fullyParallel: true,
  reporter: "list",
  use: { ...devices["Desktop Chrome"] },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
