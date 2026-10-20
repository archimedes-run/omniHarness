import { expect, test } from "@playwright/test";

/**
 * The chats list in New York (UTC-4 in October). The backend writes UTC, and
 * SQLite hands it back with no zone; a browser reads a zone-less ISO string as
 * LOCAL time, so a chat updated a moment ago read "in about 4 hours".
 *
 * NO BACKEND: threads/search is intercepted. The store side is
 * pytest's (tests/test_thread_meta_repo.py).
 */
test.use({ timezoneId: "America/New_York" });

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

test("a chat updated just now reads as just now in New York, not hours ahead", async ({
  page,
}) => {
  // "2026-10-19T16:00:00.123456": UTC, with its zone dropped, as SQLite returns it.
  const zoneless = new Date(Date.now() - 5_000).toISOString().replace("Z", "");
  await page.route("**/threads/search", (route) =>
    route.fulfill(
      json([
        {
          thread_id: "t-tz",
          status: "idle",
          created_at: zoneless,
          updated_at: zoneless,
          metadata: {},
          values: { title: "Timezone check" },
          interrupts: {},
        },
      ]),
    ),
  );
  await page.goto("/workspace/chats");

  // The browser really is in New York.
  // 240 (EDT) or 300 (EST) minutes behind UTC, depending on the day.
  expect([240, 300]).toContain(
    await page.evaluate(() => new Date().getTimezoneOffset()),
  );
  const row = page.locator("main").getByText("Timezone check");
  await expect(row).toBeVisible();
  const when = page.locator("main").getByText(/ago$|^in /);
  await expect(when).toHaveText("less than a minute ago");
});
