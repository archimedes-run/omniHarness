import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * Feature 006 chat bar, end to end: an integration removed with its chip's ×
 * is switched off for the chat, which the "+" picker shows. The gateway's
 * per-chat selection is a small stateful fake, so the picker reads back what
 * the bar wrote.
 */
function mockTools(page: Page) {
  let sources = ["connector:GOOGLECALENDAR"];
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  void page.route("**/api/tools/catalog", (route) =>
    route.fulfill(
      json({
        categories: [],
        items: [
          {
            tool_id: "connector:GOOGLECALENDAR",
            name: "Google Calendar",
            description: "",
            source: "connector",
            origin: "builtin",
            toolkit: "GOOGLECALENDAR",
            icon: null,
            category: "",
            connected: true,
            pinned: false,
          },
        ],
      }),
    ),
  );
  void page.route("**/api/threads/*/tools/count", (route) =>
    route.fulfill(json({ count: 3, cap: 40, over_cap: false })),
  );
  void page.route("**/api/threads/*/tools", (route) => {
    if (route.request().method() === "PUT") {
      sources = (route.request().postDataJSON() as { sources: string[] })
        .sources;
    }
    return route.fulfill(json({ thread_id: "t", sources, pinned: [] }));
  });
  void page.route("**/api/tool-sources*", (route) =>
    route.fulfill(
      json({
        thread_id: null,
        failing: 0,
        connectors_available: true,
        sources: [
          {
            id: "connector:GOOGLECALENDAR",
            name: "Google Calendar",
            kind: "connector",
            state: "authorised-selected",
            tool_count: null,
            error: null,
            selected: null,
          },
        ],
      }),
    ),
  );
  void page.route("**/api/threads/*/skills", (route) =>
    route.fulfill(json({ thread_id: "t", excluded: [] })),
  );
}

test("removing an integration chip with × switches it off in the picker", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  mockTools(page);
  await page.goto("/workspace/chats/new");

  const remove = page.getByRole("button", {
    name: "Remove Google Calendar from this chat",
  });
  await expect(remove).toBeVisible({ timeout: 15_000 });
  await remove.click();
  await expect(remove).toHaveCount(0);

  await page.getByRole("button", { name: "Add context" }).click();
  const picker = page.getByRole("dialog", { name: "Add context" });
  await expect(
    picker.getByRole("switch", { name: "Use Google Calendar in this chat" }),
  ).not.toBeChecked();
});
