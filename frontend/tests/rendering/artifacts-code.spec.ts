import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import {
  CLEAN_PAGE,
  installCodeStore,
  installCodeThread,
  THREAD,
  type CodeRec,
} from "./artifacts/fake-code";
import { lowContrastText } from "./contrast-probe";

/**
 * Spec 012 Slice 2 (frontend): code artifacts in the chat (a card with a
 * live thumbnail), the panel (Preview in the locked frame, Code, Ask the
 * assistant), the full page and the store (screenshots, never a live frame
 * per grid cell). Both themes at 1280 and 390 px: no sideways scroll, AA
 * text. ARTIFACT_SHOTS=<dir> saves the screenshots.
 */

test.use({
  launchOptions: {
    executablePath: process.env.CHROMIUM_EXECUTABLE ?? undefined,
  },
});

const SHOTS = process.env.ARTIFACT_SHOTS;
const PAGE_ID = "TipCalcAAAAAAAAAAAAAAA";
const REACT_ID = "CounterBBBBBBBBBBBBBBB";
const RECS: CodeRec[] = [
  { id: PAGE_ID, kind: "html", title: "Tip calculator", html: CLEAN_PAGE },
  {
    id: REACT_ID,
    kind: "react",
    title: "Counter",
    html: CLEAN_PAGE.replace("Tip calculator", "Counter").replace(
      "Add 18%",
      "+1",
    ),
    check: "failed",
    source: {
      entry: "App.tsx",
      files: {
        "App.tsx":
          'import { useState } from "react";\nimport "./styles.css";\nexport default function App() {\n  const [n, setN] = useState(0);\n  return <button onClick={() => setN(n + 1)}>Clicked {n}</button>;\n}\n',
        "styles.css":
          "button { background: var(--primary); color: var(--primary-foreground); }\n",
      },
    },
  },
];

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(800);
  await page.screenshot({ path: join(SHOTS, `${name}.png`) });
}

async function noSidewaysScroll(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    ),
  ).toBeLessThanOrEqual(1);
}

async function aa(page: Page) {
  const low = await page.evaluate(lowContrastText);
  expect(
    low,
    low.map((f) => `${f.ratio}/${f.need} "${f.text}" [${f.cls}]`).join("\n"),
  ).toEqual([]);
}

for (const theme of ["light", "dark"] as const) {
  for (const width of [1280, 390]) {
    test(`chat card, panel, code tab and store (${theme}, ${width} px)`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript((t) => {
        try {
          localStorage.setItem("theme", t);
        } catch {}
      }, theme);
      await installCodeStore(page, RECS);
      await installCodeThread(page, RECS);
      await page.goto(`/workspace/chats/${THREAD}`);
      const card = page.locator(
        `[data-testid=artifact-card][data-artifact="${PAGE_ID}"]`,
      );
      await expect(
        card.locator('[data-testid="artifact-check"]'),
      ).toContainText("Checked");
      await card.scrollIntoViewIfNeeded();
      const frame = card.locator('[data-testid="artifact-frame"]');
      await expect(frame).toBeVisible({ timeout: 15_000 });
      const inner = (await (await frame.elementHandle())!.contentFrame())!;
      await expect(inner.locator("h1")).toHaveText("Tip calculator");
      await expect
        .poll(() =>
          inner.evaluate(() =>
            document.documentElement.classList.contains("dark"),
          ),
        )
        .toBe(theme === "dark");
      await noSidewaysScroll(page);
      await aa(page);
      await card.scrollIntoViewIfNeeded();
      await shot(page, `chat-card-${theme}-${width}`);

      const panel = page.locator(
        `[data-testid=artifact-panel][data-artifact="${PAGE_ID}"]`,
      );
      // The live frame can still resize the card (its size message) as the
      // click lands, moving Open from under the pointer: press until the
      // panel opens.
      await expect(async () => {
        await card.getByTestId("artifact-card-open").click();
        await expect(panel).toBeVisible({ timeout: 1000 });
      }).toPass({ timeout: 15_000 });
      await expect(
        panel.locator('[data-testid="artifact-frame"]'),
      ).toBeVisible();
      await expect(panel.getByTestId("artifact-ask-change")).toBeVisible();
      await shot(page, `panel-preview-${theme}-${width}`);
      await panel.getByTestId("artifact-tab-code").click();
      await expect(panel.getByTestId("artifact-code")).toBeVisible();
      await aa(page);
      await shot(page, `panel-code-${theme}-${width}`);

      // "Ask the assistant" puts a reference (never the content) in the composer.
      await panel.getByTestId("artifact-ask-change").click();
      await expect(page.locator("textarea[name='message']")).toHaveValue(
        `[artifact ${PAGE_ID} v1] `,
      );

      await page.goto("/workspace/artifacts");
      const cards = page.getByTestId("artifact-store-card");
      await expect(cards).toHaveCount(2);
      await expect(
        page.locator('[data-testid="artifact-shot"]').first(),
      ).toBeVisible();
      await expect(page.locator("iframe")).toHaveCount(0);
      await noSidewaysScroll(page);
      await aa(page);
      await shot(page, `store-${theme}-${width}`);
    });
  }
}

test("react: failed check is labelled, Code shows the files, Rebuild posts the edited source", async ({
  page,
}) => {
  const log = await installCodeStore(page, RECS);
  await page.goto(`/workspace/artifacts/${REACT_ID}`);
  const panel = page.locator(
    `[data-testid=artifact-panel][data-artifact="${REACT_ID}"]`,
  );
  await expect(panel.getByTestId("artifact-check")).toContainText(
    "Layout check failed",
  );
  await expect(panel.locator('[data-testid="artifact-frame"]')).toBeVisible();
  await panel.getByTestId("artifact-tab-code").click();
  await expect(panel.getByTestId("artifact-react-files")).toContainText(
    "styles.css",
  );
  await panel.getByTestId("artifact-edit-source").click();
  await panel
    .getByTestId("artifact-source-draft")
    .fill("export default () => <p>New</p>;\n");
  await panel.getByTestId("artifact-rebuild").click();
  await expect
    .poll(() => log.writes.find((w) => w.path.endsWith("/rebuild"))?.body)
    .toMatchObject({
      base_version: 1,
      content: {
        entry: "App.tsx",
        files: { "App.tsx": "export default () => <p>New</p>;\n" },
      },
    });
  await expect(page.getByTestId("artifact-ask-change")).toHaveCount(0); // not in a chat
  await shot(page, "full-page-react-failed-light-1280");
});

test("webapp: pages by relative path in the locked frame, downloads offered", async ({
  page,
}) => {
  const id = "MySiteCCCCCCCCCCCCCCCC";
  await installCodeStore(page, [
    {
      id,
      kind: "webapp",
      title: "My site",
      html: CLEAN_PAGE,
      pages: {
        "about.html":
          "<!doctype html><html><head></head><body><h1>About us</h1></body></html>",
      },
    },
  ]);
  await page.goto(`/workspace/artifacts/${id}`);
  const panel = page.locator(
    `[data-testid=artifact-panel][data-artifact="${id}"]`,
  );
  const frame = panel.locator('[data-testid="artifact-frame"]');
  await expect(frame).toBeVisible();
  await expect(frame).toHaveAttribute("sandbox", "allow-scripts");
  await panel
    .getByTestId("artifact-webapp-pages")
    .getByRole("button", { name: "about.html" })
    .click();
  await expect(frame).toHaveAttribute("src", /&path=about\.html#n=/);
  const inner = (await (await frame.elementHandle())!.contentFrame())!;
  await expect(inner.locator("h1")).toHaveText("About us");
  // A web app downloads as its file set (.zip): no separate page download.
  await expect(panel.getByTestId("artifact-download-page")).toHaveCount(0);
  await expect(panel.getByTestId("artifact-download-source")).toHaveAttribute(
    "href",
    new RegExp(`/api/artifacts/${id}/versions/1/download$`),
  );
  await shot(page, "full-page-webapp-light-1280");
});
