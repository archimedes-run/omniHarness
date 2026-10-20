import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * Feature 006: the tool sources moved into Settings > Safety. From the
 * sidebar's More menu, Safety shows them, with a failing one's error.
 */
test("More > Safety shows the tool sources and the policy", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  await page.route("**/api/tool-sources*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        thread_id: null,
        failing: 1,
        connectors_available: false,
        sources: [
          {
            id: "local:dead-server",
            name: "dead-server",
            kind: "local",
            state: "unreachable",
            tool_count: null,
            error: "ConnectError: All connection attempts failed",
            selected: null,
          },
        ],
      }),
    }),
  );
  await page.route("**/api/policy/rules", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        source_file: "rules.yaml",
        rules: [
          { pattern: "calendar_*", tier: 3, exceptions: [], source_line: 1 },
        ],
        unreadable: false,
        kept_previous: false,
        error: null,
        threshold_targets: 10,
        expires_after_seconds: 14400,
      }),
    }),
  );

  await page.goto("/workspace/chats/new");
  await page.getByTestId("more-button").click({ timeout: 15_000 });
  await page.getByTestId("more-safety").click();
  await expect(page).toHaveURL(/\/workspace\/settings\/safety$/);

  const sources = page.getByTestId("safety-tool-sources");
  await expect(sources.getByTestId("safety-source")).toHaveCount(1);
  await expect(sources).toContainText("dead-server");
  await expect(sources).toContainText("Unreachable");
  await expect(sources).toContainText(
    "ConnectError: All connection attempts failed",
  );
  await expect(page.getByTestId("rule")).toContainText("calendar_*");
});
