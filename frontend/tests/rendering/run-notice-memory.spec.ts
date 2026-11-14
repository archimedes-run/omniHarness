import { expect, test, type Page } from "@playwright/test";

import { THREAD, json, stub } from "./chat-bar-stubs";
import { lowContrastText } from "./contrast-probe";

/**
 * A reply cut off by a gateway restart, and "Memory off in this chat", in
 * both themes at desktop and phone width:
 *
 * - the notice is a system notice: its words, what "Try again" will send
 *   (clipped, with Show all), "Attachments are not re-sent." and the button;
 *   the actions that had already run as the disclosure note;
 * - "Try again" sends the person's message as a new run, exactly once even
 *   when double-clicked;
 * - the memory chip with its way back, and the composer toggle;
 * - no sideways scroll, and every text meets WCAG AA (contrast-probe).
 *
 * NO BACKEND: the thread's state, history and every chat-page call are
 * intercepted.
 */
const NOTICE = "This reply was interrupted by a restart. Ask again.";
const DISCLOSED = "\n\nRan without asking: write_file";
// Long enough to be clipped to two lines at desktop width too.
const RETRY = [
  "Draft the launch notes for the beta from the changelog and the open",
  "tasks in the OmniHarness project, then list what is still blocking the",
  "release, who owns each blocker, and the date each one is due, grouped by",
  "area, with the riskiest item first and a one-line summary at the end.",
].join(" ");

function threadState() {
  return {
    values: {
      title: "Launch notes",
      messages: [
        { type: "human", id: "h1", content: RETRY },
        {
          type: "ai",
          id: "run-interrupted-r1",
          content: NOTICE + DISCLOSED,
          additional_kwargs: {
            omniharness_run_notice: {
              kind: "interrupted",
              reason: "restart",
              run_id: "r1",
              retry_text: RETRY,
              had_attachments: true,
              automation: false,
            },
            omniharness_disclosure: {
              text: DISCLOSED,
              items: [
                {
                  tool: "write_file",
                  text: "write_file on notes.md",
                  agent: "",
                  grant: false,
                },
              ],
              sources: [],
            },
          },
        },
      ],
    },
    next: [],
    tasks: [],
    metadata: {},
    created_at: new Date().toISOString(),
    checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
    parent_checkpoint: null,
  };
}

interface Seen {
  /** The text of each run the browser started. */
  runs: string[];
  memoryPuts: unknown[];
}

async function open(page: Page, scheme: "light" | "dark") {
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
  // The chat bar's API first; the routes below take precedence over it.
  await stub(page);
  const seen: Seen = { runs: [], memoryPuts: [] };
  const state = threadState();
  await page.route("**/api/langgraph/**", (route) => {
    const request = route.request();
    const url = request.url();
    if (request.method() === "POST" && /\/runs(\/stream)?(\?|$)/.test(url)) {
      const body = request.postDataJSON() as {
        input?: {
          messages?: { content: { type: string; text: string }[] }[];
        };
      };
      const content = body.input?.messages?.[0]?.content ?? [];
      seen.runs.push(content.map((c) => c.text).join(""));
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: "",
      });
    }
    if (url.includes("/history")) return json(route, [state]);
    if (url.includes("/runs") || url.includes("/search"))
      return json(route, []);
    return json(route, state);
  });
  await page.route("**/api/confirmations", (route) =>
    json(route, { actions: [], readable: true, error: "" }),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    json(route, { alerts: [], waiting_count: 0 }),
  );
  await page.route("**/api/threads/*/builder", (route) =>
    json(route, { thread_id: THREAD, building: null }),
  );
  await page.route("**/api/threads/*/memory", (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as { memory_off: boolean };
      seen.memoryPuts.push(body);
      return json(route, {
        thread_id: THREAD,
        memory_off: body.memory_off,
        source: body.memory_off ? "toggle" : null,
      });
    }
    return json(route, {
      thread_id: THREAD,
      memory_off: true,
      source: "message",
    });
  });
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  return seen;
}

const VIEWPORTS = [
  { width: 1280, height: 900 },
  { width: 390, height: 844 },
];

for (const scheme of ["light", "dark"] as const) {
  for (const viewport of VIEWPORTS) {
    test.describe(`${scheme} ${viewport.width}x${viewport.height}`, () => {
      test.use({ colorScheme: scheme, viewport });

      test("the interrupted notice and the memory chip render, fit, and meet AA", async ({
        page,
      }) => {
        await open(page, scheme);
        expect(
          await page.evaluate(() =>
            document.documentElement.classList.contains("dark"),
          ),
        ).toBe(scheme === "dark");

        const notice = page.getByTestId("run-notice");
        await expect(notice).toBeVisible();
        await expect(notice).toContainText(NOTICE);
        // The disclosure is the note under it, not part of the sentence.
        await expect(notice.getByTestId("disclosure-note")).toContainText(
          "Ran without asking: write_file",
        );
        const preview = notice.getByTestId("run-notice-preview");
        await expect(preview).toBeVisible();
        await expect(preview).toContainText("Sends again:");
        const toggle = preview.getByRole("button", { name: "Show all" });
        await expect(toggle).toBeVisible();
        await expect(toggle).toHaveAttribute("aria-expanded", "false");
        await expect(
          notice.getByText("Attachments are not re-sent."),
        ).toBeVisible();
        await expect(
          notice.getByRole("button", { name: "Try again" }),
        ).toBeVisible();

        const chip = page.getByTestId("memory-off-chip");
        await expect(chip).toBeVisible();
        await expect(chip).toContainText("Memory off in this chat");
        await expect(
          chip.getByRole("button", { name: "Turn memory back on" }),
        ).toBeVisible();
        await expect(
          page.getByRole("button", { name: "Don't use memory in this chat" }),
        ).toBeVisible();

        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= window.innerWidth,
          ),
          "the page scrolls sideways",
        ).toBe(true);

        const found = await page.evaluate(lowContrastText);
        expect(
          found,
          found
            .map(
              (f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`,
            )
            .join("\n"),
        ).toEqual([]);

        // Opened, it is still AA and still fits.
        await toggle.click();
        await expect(
          preview.getByRole("button", { name: "Show less" }),
        ).toHaveAttribute("aria-expanded", "true");
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= window.innerWidth,
          ),
        ).toBe(true);
        expect(await page.evaluate(lowContrastText)).toEqual([]);
      });

      test("Try again sends the person's message once, even on a double-click", async ({
        page,
      }) => {
        const seen = await open(page, scheme);
        const retry = page
          .getByTestId("run-notice")
          .getByRole("button", { name: "Try again" });
        await expect(retry).toBeEnabled();
        expect(seen.runs).toEqual([]);
        await retry.dblclick();
        await expect.poll(() => seen.runs.length).toBe(1);
        // Once sent, the button stays off after the run is over (the stub's
        // run ends at once), so a later click cannot send it again either.
        // (A double-click alone is also absorbed by the send-in-flight guard
        // in useThreadStream; this click is what proves the notice's own.)
        await expect(retry).toBeDisabled();
        await retry.click({ force: true });
        // Give a second send every chance to leave the browser.
        await page.waitForTimeout(500);
        expect(seen.runs).toEqual([RETRY]);
      });
    });
  }
}
