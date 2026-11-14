import { expect, test } from "@playwright/test";

import { demoApp, installFakeBridge } from "./apps/fake-bridge";

/**
 * Spec 011 FR-031: opening an app with a warm server cache renders every
 * tile with data in under 2 s, p95 of 10 loads. Measured from the host
 * page's navigation start to the moment the demo app rendered its last tile
 * (both as epoch milliseconds: performance.timeOrigin + now), against the
 * fake bridge answering at once (a warm cache). PR 4 repeats it on the live
 * stack.
 *
 * The bridge's answers are delayed APPS_PERF_BRIDGE_MS (default 50 ms) to
 * stand for the gateway's own time on a cache hit.
 */

test.use({ timezoneId: "UTC" });

test("warm-cache open renders every tile in under 2 s (p95 of 10)", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await installFakeBridge(page, {
    apps: [demoApp()],
    delayMs: Number(process.env.APPS_PERF_BRIDGE_MS ?? 50),
  });
  // One load first: the build's chunks into the browser cache, as for a
  // pinned app opened before.
  await page.goto("/workspace/apps/today");
  const times: number[] = [];
  for (let i = 0; i < 10; i++) {
    await page.goto("/workspace/apps/today");
    const navStart = await page.evaluate(() => performance.timeOrigin);
    const handle = await page
      .locator('[data-testid="app-frame"]')
      .elementHandle();
    const frame = (await handle!.contentFrame())!;
    await expect
      .poll(() => frame.evaluate(() => document.body?.dataset.rendered ?? ""), {
        timeout: 10_000,
        intervals: [25],
      })
      .toBe("all");
    const renderedAt = await frame.evaluate(
      () => (window as unknown as { __renderedAt: number }).__renderedAt,
    );
    times.push(Math.round(renderedAt - navStart));
  }
  const sorted = [...times].sort((a, b) => a - b);
  const p95 = sorted[Math.ceil(0.95 * sorted.length) - 1]!;
  console.log(`apps warm open (ms): ${times.join(", ")}; p95 ${p95}`);
  test.info().annotations.push({ type: "p95_ms", description: String(p95) });
  expect(p95).toBeLessThan(2000);
});
