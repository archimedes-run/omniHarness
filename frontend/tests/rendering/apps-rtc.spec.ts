import { createSocket, type Socket } from "node:dgram";
import { networkInterfaces } from "node:os";

import { expect, test, type Page } from "@playwright/test";

import {
  demoApp,
  installFakeBridge,
  type BridgeOptions,
} from "./apps/fake-bridge";
import { rtcScript } from "./apps/rtc-app";

/**
 * Spec 011 FR-018: no WebRTC from any realm an app can make. CSP does not
 * govern WebRTC, so the shim removes it from the app's realm; these specs
 * look for a realm the shim never ran in (a srcdoc child running the app's
 * own script, a frame's initial about:blank realm, an XSLT-made frame) and
 * assert on a local UDP listener's log: no STUN packet arrives.
 *
 * Two layers, each tested on its own as well as together:
 * - the app CSP's Trusted Types directives (no HTML or script from strings:
 *   srcdoc, innerHTML, insertAdjacentHTML, setAttribute("srcdoc") throw);
 * - the shim (no frame elements at all, and no HTML strings naming one).
 *
 * Sabotage: APPS_SABOTAGE_FRAME_CSP=no-trusted-types fails the CSP-only test;
 * removing the shim's frame refusal fails the shim-only test.
 */

test.use({
  timezoneId: "UTC",
  launchOptions: {
    executablePath: process.env.CHROMIUM_EXECUTABLE ?? undefined,
    args: [
      "--disable-features=LocalNetworkAccessChecks,PrivateNetworkAccessSendPreflights,PrivateNetworkAccessRespectPreflightResults,BlockInsecurePrivateNetworkRequests",
    ],
  },
});

let udp: Socket;
let target = "";
const packets: string[] = [];

/** A non-loopback IPv4 address if there is one: WebRTC may not use loopback. */
function address(): string {
  for (const list of Object.values(networkInterfaces())) {
    for (const a of list ?? []) {
      if (a.family === "IPv4" && !a.internal) return a.address;
    }
  }
  return "127.0.0.1";
}

test.beforeAll(async () => {
  udp = createSocket("udp4");
  udp.on("message", (_msg, rinfo) =>
    packets.push(`${rinfo.address}:${rinfo.port}`),
  );
  await new Promise<void>((resolve) => udp.bind(0, "0.0.0.0", resolve));
  target = `${address()}:${udp.address().port}`;
});

test.afterAll(() => {
  udp.close();
});

test.beforeEach(() => {
  packets.length = 0;
});

const ALL = [
  "top",
  "srcdoc-create",
  "srcdoc-innerhtml",
  "srcdoc-adjacent",
  "srcdoc-attribute",
  "blank-create",
  "blank-innerhtml",
  "xslt",
];

async function run(page: Page, vectors: string[], over: BridgeOptions = {}) {
  const hello = over.withoutShim === true;
  await installFakeBridge(page, {
    apps: [
      demoApp({
        id: "rtc",
        name: "RTC",
        sources: ["calendar"],
        script: rtcScript(target, vectors, { hello }),
        body: "<main><p>rtc</p></main>",
      }),
    ],
    ...over,
  });
  await page.goto("/workspace/apps/rtc");
  const handle = await page
    .locator('[data-testid="app-frame"]')
    .elementHandle();
  const frame = (await handle!.contentFrame())!;
  await expect
    .poll(() => frame.evaluate(() => document.body?.dataset.rtcDone ?? ""))
    .toBe("1");
  // ICE gathering sends its STUN requests within a second or two.
  await page.waitForTimeout(3000);
  return frame.evaluate(
    () => (window as unknown as { __rtc: Record<string, string> }).__rtc,
  );
}

test("no STUN packet leaves from any realm: shim and Trusted Types together", async ({
  page,
}) => {
  const result = await run(page, ALL);
  expect(packets, JSON.stringify(result)).toEqual([]);
  expect(result.top).toBe("no-rtc");
});

test("the CSP's Trusted Types alone stop the srcdoc and HTML-string realms", async ({
  page,
}) => {
  // No shim at all: only the app document's CSP stands.
  const result = await run(
    page,
    [
      "srcdoc-create",
      "srcdoc-innerhtml",
      "srcdoc-adjacent",
      "srcdoc-attribute",
      "blank-innerhtml",
    ],
    { withoutShim: true },
  );
  expect(packets, JSON.stringify(result)).toEqual([]);
  for (const v of [
    "srcdoc-create",
    "srcdoc-innerhtml",
    "srcdoc-adjacent",
    "srcdoc-attribute",
    "blank-innerhtml",
  ]) {
    expect(result[v], v).toMatch(/TrustedHTML|Trusted Type|TrustedScript/);
  }
});

test("the shim alone stops every frame realm, created or written", async ({
  page,
}) => {
  // The CSP without its Trusted Types directives: only the shim stands.
  const result = await run(page, ALL, { trustedTypes: false });
  expect(packets, JSON.stringify(result)).toEqual([]);
  for (const v of ALL) expect(result[v], v).not.toBe("started");
});
