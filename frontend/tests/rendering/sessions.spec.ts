import { expect, test, type Page } from "@playwright/test";

/**
 * T069 — the sessions surface, asserted against what renders (SC-006, SC-007).
 *
 * NO BACKEND: /api/sessions is intercepted. The four watcher conditions, over
 * the real watcher, are pytest's (tests/gateway/test_sessions_router.py).
 */

function session(state: string, epistemic: string, project: string) {
  return {
    session_id: `${project}-0000`,
    project,
    display_state: state,
    epistemic,
    last_activity_at: null,
    quiet_seconds: 120,
    summary: "",
    summary_provenance: "mechanical",
    relay_suppressed: false,
    withheld: false,
  };
}

const LIVE = {
  reachable: true,
  unreachable_kind: null,
  unreachable_detail: null,
  observability: "live",
  staleness_seconds: 2,
  as_of: null,
  observe_only: true,
  observe_only_reason: "Sessions are observed, never controlled.",
  sessions: [
    session("waiting-on-user", "inferred", "darcy-repo"),
    session("completed", "observed", "rallion"),
  ],
};

async function serve(page: Page, body: Record<string, unknown>) {
  await page.route("**/api/sessions", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    }),
  );
  await page.goto("/workspace/sessions");
}

test("with the watcher stopped the page says sessions cannot be seen, and renders no list (SC-006)", async ({
  page,
}) => {
  await serve(page, {
    ...LIVE,
    reachable: false,
    unreachable_kind: "unreachable",
    unreachable_detail: "ConnectError",
    observability: null,
    sessions: null,
  });

  await expect(page.getByTestId("watcher-health")).toHaveAttribute(
    "data-health",
    "cannot-see",
  );
  await expect(page.getByTestId("watcher-health")).toContainText(
    "cannot see your sessions",
  );
  await expect(page.getByTestId("empty")).toHaveCount(0);
  await expect(page.getByTestId("session")).toHaveCount(0);
});

test("a waiting session differs from a finished one without reading the text (SC-007)", async ({
  page,
}) => {
  await serve(page, LIVE);

  const waiting = page.locator(
    '[data-testid="session"][data-state="waiting-on-user"]',
  );
  const finished = page.locator(
    '[data-testid="session"][data-state="completed"]',
  );
  const border = (l: typeof waiting) =>
    l.evaluate((el) => getComputedStyle(el).borderTopStyle);
  expect(await border(waiting)).toBe("dashed");
  expect(await border(finished)).toBe("solid");
  await expect(waiting.getByTestId("epistemic-icon")).toHaveAttribute(
    "aria-label",
    "inferred",
  );
  await expect(finished.getByTestId("epistemic-icon")).toHaveAttribute(
    "aria-label",
    "observed",
  );
});

test("stale data says how stale, and still shows the last-known sessions", async ({
  page,
}) => {
  await serve(page, {
    ...LIVE,
    observability: "stale",
    staleness_seconds: 7200,
  });

  await expect(page.getByTestId("watcher-health")).toHaveAttribute(
    "data-health",
    "stale",
  );
  await expect(page.getByTestId("watcher-health")).toContainText(
    "Last seen 2 h ago",
  );
  await expect(page.getByTestId("session")).toHaveCount(2);
});

test("observe-only is stated, so the missing controls read as a property (FR-015)", async ({
  page,
}) => {
  await serve(page, LIVE);

  await expect(page.getByTestId("observe-only")).toContainText(
    "observed, never controlled",
  );
});

test("a summary that failed redaction shows as withheld, not as blank (FR-031, SC-015)", async ({
  page,
}) => {
  await serve(page, {
    ...LIVE,
    sessions: [
      {
        ...session("working", "observed", "darcy-repo"),
        summary:
          "Withheld: this could not be safely redacted for display. Check it locally.",
        withheld: true,
      },
    ],
  });

  await expect(page.getByTestId("withheld")).toBeVisible();
  await expect(page.getByTestId("withheld")).toContainText("Withheld");
});

test("a watcher that did not answer in time shows its last answer, labelled with its age", async ({
  page,
}) => {
  await serve(page, {
    ...LIVE,
    reachable: false,
    unreachable_kind: "unreachable",
    unreachable_detail: "TimeoutError",
    last_known_age_seconds: 40,
  });

  await expect(page.getByTestId("watcher-health")).toHaveAttribute(
    "data-health",
    "last-known",
  );
  await expect(page.getByTestId("watcher-health")).toContainText("40s ago");
  await expect(page.getByTestId("session")).toHaveCount(2);
});
