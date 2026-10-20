import { expect, test, type Page } from "@playwright/test";

/**
 * Phase 2.6 — Settings → Memory, redesigned, asserted against what renders.
 *
 * NO BACKEND: /api/memory and its write routes are intercepted. The routes'
 * own behaviour (section edit, cleanup preview/apply, the durability scrub) is
 * pytest's (tests/test_memory_durability.py).
 */
const DAY = 24 * 60 * 60 * 1000;
const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString();

const LONG =
  "Building OmniHarness, a self-hosted agent platform, toward a public beta. " +
  "Running a HackMIT 2026 judging workflow with a small team, and tracking " +
  "which sponsors need follow-up. Learning Rust in the evenings for a " +
  "watcher rewrite. Planning a board update for the retention dashboard " +
  "next month, with numbers from the cohort analysis.";

function memory(overrides: Record<string, unknown> = {}) {
  return {
    version: "1.0",
    lastUpdated: ago(1),
    user: {
      workContext: {
        summary:
          "Founder building OmniHarness. Works mostly in Python and TypeScript.",
        updatedAt: ago(3),
      },
      personalContext: {
        summary: "Prefers concise answers with a table first.",
        updatedAt: ago(100),
      },
      topOfMind: { summary: LONG, updatedAt: ago(2) },
    },
    history: {
      recentMonths: { summary: "", updatedAt: "" },
      earlierContext: { summary: "", updatedAt: "" },
      longTermBackground: { summary: "", updatedAt: "" },
    },
    facts: [
      {
        id: "f1",
        content: "Prefers tables over prose",
        category: "preference",
        confidence: 0.95,
        createdAt: ago(10),
        source: "t1",
      },
      {
        id: "f2",
        content: "Lives in New York",
        category: "context",
        confidence: 0.9,
        createdAt: ago(40),
        source: "t2",
      },
      {
        id: "f3",
        content: "Collaborates with Darcy on scheduling",
        category: "context",
        confidence: 0.9,
        createdAt: ago(5),
        source: "t3",
      },
      {
        id: "f4",
        content: "Learning Rust",
        category: "goal",
        confidence: 0.8,
        createdAt: ago(20),
        source: "t4",
      },
      {
        id: "f5",
        content: "Uses Telegram for alerts",
        category: "preference",
        confidence: 0.9,
        createdAt: ago(1),
        source: "t5",
      },
    ],
    ...overrides,
  };
}

type Write = { method: string; url: string; body: unknown };

async function serve(
  page: Page,
  data: unknown = memory(),
  path = "/workspace/settings/memory",
) {
  const writes: Write[] = [];
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await page.route("**/api/memory**", (route) => {
    const req = route.request();
    if (
      req.method() === "GET" &&
      new URL(req.url()).pathname === "/api/memory"
    ) {
      return route.fulfill(json(data));
    }
    writes.push({
      method: req.method(),
      url: req.url(),
      body: req.postDataJSON(),
    });
    if (req.url().includes("/cleanup/preview")) {
      return route.fulfill(
        json({
          version: "v",
          sections: [
            {
              group: "user",
              key: "topOfMind",
              before:
                "Building a dashboard. Saved it to /mnt/user-data/outputs/a.md.",
              after: "Building a dashboard.",
              changed: true,
            },
          ],
          factsToRemove: [
            {
              id: "f9",
              content: "Wrote /mnt/user-data/outputs/a.md",
              markers: ["unix path"],
            },
          ],
        }),
      );
    }
    return route.fulfill(json(data));
  });
  await page.goto(path);
  return writes;
}

const overlap = (a: DOMRect | null, b: DOMRect | null) =>
  !!a &&
  !!b &&
  a.left < b.right &&
  b.left < a.right &&
  a.top < b.bottom &&
  b.top < a.bottom;

for (const width of [1280, 640, 380]) {
  test(`at ${width}px the tabs never overlap the toolbar buttons`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await serve(page);
    const tabs = await page.getByRole("tablist").boundingBox();
    const add = await page
      .getByRole("button", { name: "Add fact" })
      .boundingBox();
    const more = await page
      .getByRole("button", { name: "More memory actions" })
      .boundingBox();
    expect(tabs && add && more, "toolbar parts not rendered").toBeTruthy();
    const box = (b: typeof tabs) =>
      b
        ? ({
            left: b.x,
            right: b.x + b.width,
            top: b.y,
            bottom: b.y + b.height,
          } as DOMRect)
        : null;
    expect(overlap(box(tabs), box(add))).toBe(false);
    expect(overlap(box(tabs), box(more))).toBe(false);
    // No empty icon-only button without a name (the old toolbar had one).
    for (const button of await page
      .getByTestId("memory-toolbar")
      .getByRole("button")
      .all()) {
      expect(
        (await button.getAttribute("aria-label")) ??
          (await button.innerText()).trim(),
      ).not.toBe("");
    }
  });
}

test("one primary action; import, export, clean up and clear live in the ⋯ menu", async ({
  page,
}) => {
  await serve(page);
  await expect(page.getByRole("button", { name: "Add fact" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: /import|export|clear/i }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "More memory actions" }).click();
  for (const item of [
    "Import…",
    "Export",
    "Clean up memory…",
    "Clear all memory…",
  ]) {
    await expect(page.getByRole("menuitem", { name: item })).toBeVisible();
  }
});

test("summaries are calm cards: plain text, a muted updated line, no markdown", async ({
  page,
}) => {
  await serve(page);
  const cards = page.getByTestId("summary-card");
  await expect(cards).toHaveCount(3);
  await expect(cards.nth(0)).toContainText("Work");
  await expect(cards.nth(0).getByTestId("updated")).toContainText(
    "Updated 3 days ago",
  );
  for (const card of await cards.all()) {
    await expect(
      card.locator("code, blockquote, h1, h2, h3:not(:first-child)"),
    ).toHaveCount(0);
  }
});

test("a long summary collapses behind Show more; an old one says it may be out of date", async ({
  page,
}) => {
  await serve(page);
  const top = page.locator('[data-section="user.topOfMind"]');
  await expect(top.getByRole("button", { name: "Show more" })).toBeVisible();
  await top.getByRole("button", { name: "Show more" }).click();
  await expect(top.getByRole("button", { name: "Show less" })).toBeVisible();
  await expect(
    page.locator('[data-section="user.personalContext"]').getByTestId("stale"),
  ).toContainText("may be out of date");
  await expect(
    page.locator('[data-section="user.workContext"]').getByTestId("stale"),
  ).toHaveCount(0);
});

test("a summary can be corrected inline and saved", async ({ page }) => {
  const writes = await serve(page);
  const work = page.locator('[data-section="user.workContext"]');
  await work.hover();
  await work.getByRole("button", { name: "Edit Work" }).click();
  await work.getByRole("textbox").fill("Founder of OmniHarness.");
  await work.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]!.method).toBe("PUT");
  expect(writes[0]!.url).toContain("/api/memory/sections/user/workContext");
  expect(writes[0]!.body).toEqual({ summary: "Founder of OmniHarness." });
});

test("facts are searchable, with a category chip and when they were learned", async ({
  page,
}) => {
  await serve(page, memory(), "/workspace/settings/memory?tab=facts");
  await expect(page.getByTestId("fact")).toHaveCount(5);
  await page.getByLabel("Search facts").fill("rust");
  await expect(page.getByTestId("fact")).toHaveCount(1);
  await expect(page.getByTestId("fact")).toContainText("goal");
  await expect(page.getByTestId("fact")).toContainText("learned 20 days ago");
  await page.getByLabel("Search facts").fill("zzz");
  await expect(page.getByTestId("facts-none")).toBeVisible();
});

test("Forget this is one click, and Undo puts the fact back", async ({
  page,
}) => {
  const writes = await serve(
    page,
    memory(),
    "/workspace/settings/memory?tab=facts",
  );
  const row = page.getByTestId("fact").filter({ hasText: "Learning Rust" });
  await row.hover();
  await row.getByRole("button", { name: "Forget this" }).click();
  await expect.poll(() => writes.map((w) => w.method)).toEqual(["DELETE"]);
  expect(writes[0]!.url).toContain("/api/memory/facts/f4");
  await page.getByRole("button", { name: "Undo" }).click();
  await expect
    .poll(() => writes.map((w) => w.method))
    .toEqual(["DELETE", "POST"]);
  expect(writes[1]!.body).toEqual({
    content: "Learning Rust",
    category: "goal",
    confidence: 0.8,
  });
});

test("clearing all memory takes typing CLEAR", async ({ page }) => {
  const writes = await serve(page);
  await page.getByRole("button", { name: "More memory actions" }).click();
  await page.getByRole("menuitem", { name: "Clear all memory…" }).click();
  const confirm = page.getByRole("button", { name: "Clear all memory" });
  await expect(confirm).toBeDisabled();
  await page.getByLabel("Type CLEAR to confirm").fill("clear");
  await expect(confirm).toBeDisabled();
  await page.getByLabel("Type CLEAR to confirm").fill("CLEAR");
  await confirm.click();
  await expect.poll(() => writes.map((w) => w.method)).toEqual(["DELETE"]);
});

test("the cleanup shows before and after, and applies only what is accepted", async ({
  page,
}) => {
  const writes = await serve(page);
  await page.getByRole("button", { name: "More memory actions" }).click();
  await page.getByRole("menuitem", { name: "Clean up memory…" }).click();
  const section = page.getByTestId("cleanup-section");
  await expect(section).toContainText("Top of mind");
  await expect(section.locator("del")).toContainText(
    "/mnt/user-data/outputs/a.md",
  );
  // Keep the fact: untick it, apply the section only.
  await page.getByRole("checkbox", { name: /Wrote/ }).uncheck();
  await page.getByRole("button", { name: "Apply 1 change" }).click();
  await expect
    .poll(() => writes.map((w) => new URL(w.url).pathname))
    .toEqual(["/api/memory/cleanup/preview", "/api/memory/cleanup/apply"]);
  expect(writes[1]!.body).toEqual({
    version: "v",
    sections: { "user.topOfMind": "Building a dashboard." },
    factsToRemove: [],
  });
});

test("an empty memory says what will appear here, and loading shows placeholders", async ({
  page,
}) => {
  const empty = memory({
    user: {
      workContext: { summary: "", updatedAt: "" },
      personalContext: { summary: "", updatedAt: "" },
      topOfMind: { summary: "", updatedAt: "" },
    },
    facts: [],
  });
  await page.route("**/api/memory", async (route) => {
    await new Promise((r) => setTimeout(r, 600));
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(empty),
    });
  });
  await page.goto("/workspace/settings/memory");
  await expect(page.getByTestId("memory-loading")).toBeVisible();
  await expect(page.getByTestId("memory-empty")).toBeVisible();
  await expect(page.getByTestId("memory-loading")).toHaveCount(0);
});
