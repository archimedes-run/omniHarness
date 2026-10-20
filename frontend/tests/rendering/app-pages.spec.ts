import { expect, test } from "@playwright/test";

/**
 * Feature 006 pages without a board (Chats list, Coding sessions): the same
 * Graphite page as the boards: a 24 px title, no breadcrumb header (the top
 * bar names the page), and the boards' divided rows.
 */
const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

test("Chats: a title, a search, one row per chat, no breadcrumb header", async ({
  page,
}) => {
  await page.route("**/threads/search", (route) =>
    route.fulfill(
      json([
        {
          thread_id: "th1",
          updated_at: new Date().toISOString(),
          values: { title: "Calendar cleanup" },
          metadata: {},
        },
        {
          thread_id: "th2",
          updated_at: new Date().toISOString(),
          values: { title: "Feature 005 slice review" },
          metadata: {},
        },
      ]),
    ),
  );
  await page.goto("/workspace/chats");
  const h1 = page.getByRole("heading", { level: 1, name: "Chats" });
  await expect(h1).toBeVisible();
  expect(await h1.evaluate((el) => getComputedStyle(el).fontSize)).toBe("24px");
  const rows = page.getByTestId("chats-list").getByRole("link");
  await expect(rows).toHaveCount(2);
  await page.getByRole("searchbox", { name: "Search chats" }).fill("calendar");
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText("Calendar cleanup");
  // The old page header: a breadcrumb and a GitHub link. Gone.
  await expect(
    page.getByRole("navigation", { name: /breadcrumb/i }),
  ).toHaveCount(0);
  await expect(page.locator("main a[href*='github.com']")).toHaveCount(0);
});

test("Coding sessions: the board's title and cards", async ({ page }) => {
  await page.route("**/api/sessions", (route) =>
    route.fulfill(
      json({
        reachable: true,
        unreachable_kind: null,
        unreachable_detail: null,
        observability: "live",
        staleness_seconds: 2,
        as_of: null,
        observe_only: true,
        observe_only_reason: "Sessions are observed, never controlled.",
        sessions: [
          {
            session_id: "s-1",
            project: "omniHarness@main",
            display_state: "working",
            epistemic: "observed",
            last_activity_at: new Date().toISOString(),
            quiet_seconds: 10,
            summary: "Writing the parser.",
            summary_provenance: "mechanical",
            relay_suppressed: false,
            withheld: false,
          },
        ],
      }),
    ),
  );
  await page.goto("/workspace/sessions");
  const h1 = page.getByRole("heading", { level: 1, name: "Coding sessions" });
  expect(await h1.evaluate((el) => getComputedStyle(el).fontSize)).toBe("24px");
  const card = page.getByTestId("session");
  await expect(card).toContainText("omniHarness@main");
  expect(
    await card.evaluate((el) => getComputedStyle(el).borderTopLeftRadius),
  ).toBe("14px");
});
