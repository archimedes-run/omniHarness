/**
 * Can this environment run a RENDERING assertion?
 *
 * Not a product test. A measurement, run to settle one question:
 * frontend/docs/FRONTEND_TESTING_GAP.md records that a browser bundle cannot be
 * produced locally — repeated clean installs leave the directory at 448 KB
 * against ~350 MB — and concludes the frontend has no Article XI equivalent.
 *
 * That conclusion assumed the constraint is universal. It may be local: CI
 * already installs Playwright for the e2e job. If CI can launch a browser and
 * read a computed style, the gap is an inconvenience for local development
 * rather than a hole in what can be asserted at all — and Feature 004's
 * acceptance criteria can be written about what a user SEES.
 *
 * Deliberately standalone. The e2e suite has been red since June because its
 * workflow starts no backend, so a result buried in there proves nothing about
 * the browser.
 *
 * Deliberately assertion-shaped rather than a smoke test: launching is not the
 * capability in question. Reading back a computed value that only a real layout
 * and cascade can produce is.
 */

import { expect, test } from "@playwright/test";

const PAGE = `
<!doctype html>
<html>
  <head>
    <style>
      :root { --probe-bg: rgb(17, 34, 51); }
      .dark { --probe-bg: rgb(238, 221, 204); }
      body { background-color: var(--probe-bg); margin: 0; }
      #box { width: 120px; height: 40px; color: var(--probe-bg); }
    </style>
  </head>
  <body><div id="box">probe</div></body>
</html>`;

test("a browser launches and renders a page", async ({ page }) => {
  await page.setContent(PAGE);

  await expect(page.locator("#box")).toBeVisible();
});

test("a computed style can be read back", async ({ page }) => {
  await page.setContent(PAGE);

  const background = await page.evaluate(
    () => getComputedStyle(document.body).backgroundColor,
  );

  // The literal resolved value, not the variable. Only a real cascade produces this.
  expect(background).toBe("rgb(17, 34, 51)");
});

test("a class toggle changes what is computed — the assertion the gap is about", async ({
  page,
}) => {
  await page.setContent(PAGE);

  const before = await page.evaluate(
    () => getComputedStyle(document.body).backgroundColor,
  );
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  const after = await page.evaluate(
    () => getComputedStyle(document.body).backgroundColor,
  );

  expect(before).toBe("rgb(17, 34, 51)");
  expect(after).toBe("rgb(238, 221, 204)");
  expect(after).not.toBe(before);
});

test("layout is real, not a stub", async ({ page }) => {
  await page.setContent(PAGE);

  const box = await page.locator("#box").boundingBox();

  expect(box?.width).toBe(120);
  expect(box?.height).toBe(40);
});
