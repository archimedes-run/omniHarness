import { expect, test } from "@playwright/test";

/**
 * Spec 012 S2: every non-Apps page frames only page-csp.js FRAME_PATHS (no
 * bare 'self', no blob:). The frames those pages already use keep working:
 * the mermaid frame, a chat's file previews and live preview sessions, and
 * the html fallback (now srcdoc, which frame-src does not govern).
 */

test.use({
  launchOptions: {
    executablePath: process.env.CHROMIUM_EXECUTABLE ?? undefined,
  },
});

test("each allowed frame path loads; other paths and blob: are refused; srcdoc still runs", async ({
  page,
}) => {
  const msgs: string[] = [];
  page.on("console", (m) => msgs.push(m.text()));
  await page.route("**/api/threads/t/artifacts/**", (r) =>
    r.fulfill({ status: 200, contentType: "text/html", body: "<p>file</p>" }),
  );
  await page.route("**/api/threads/t/previews/p/proxy/**", (r) =>
    r.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<p>preview</p>",
    }),
  );
  await page.goto("/workspace/chats/new");
  const cases: [string, boolean][] = [
    ["/mermaid-frame/frame.html", false],
    ["/api/threads/t/artifacts/mnt/user-data/outputs/a.html", false],
    ["/api/threads/t/previews/p/proxy/", false],
    ["/workspace/settings", true],
    ["blob:", true],
  ];
  for (const [src, refusedExpected] of cases) {
    msgs.length = 0;
    await page.evaluate(async (s) => {
      const f = document.createElement("iframe");
      f.src =
        s === "blob:"
          ? URL.createObjectURL(new Blob(["<p>x</p>"], { type: "text/html" }))
          : s;
      document.body.appendChild(f);
      await new Promise((r) => setTimeout(r, 800));
    }, src);
    expect(
      msgs.some((m) => m.includes("frame-src")),
      src,
    ).toBe(refusedExpected);
  }
  const ran = await page.evaluate(async () => {
    const f = document.createElement("iframe");
    f.setAttribute("sandbox", "allow-scripts allow-forms");
    f.srcdoc = "<script>parent.postMessage('srcdoc-ran','*')</script>";
    const got = new Promise((r) =>
      window.addEventListener(
        "message",
        (e) => e.data === "srcdoc-ran" && r(true),
      ),
    );
    document.body.appendChild(f);
    return Promise.race([
      got,
      new Promise((r) => setTimeout(() => r(false), 2000)),
    ]);
  });
  expect(ran).toBe(true);
});

const DEMO = "fe3f7974-1bcb-4a01-a950-79673baafefd";
const DEMO_PAGE = `/mock/api/threads/${DEMO}/artifacts/mnt/user-data/outputs/index.html`;

test("every page frames /mock/api/threads/, whatever its URL", async ({
  page,
}) => {
  for (const url of [
    "/workspace/chats/new",
    "/workspace/chats/new?mock=true",
  ]) {
    const doc = page.waitForResponse(
      (r) => r.request().resourceType() === "document",
    );
    await page.goto(url);
    const frameSrc = /frame-src ([^;]+)/.exec(
      (await doc).headers()["content-security-policy"] ?? "",
    )![1]!;
    expect(frameSrc, url).toContain("/mock/api/threads/");
    expect(frameSrc).not.toMatch(/blob:|'self'/);
  }
});

test("a demo HTML page framed by the app cannot run script (its sandbox header)", async ({
  page,
}) => {
  // The demo page's own response, with one script added that would report back.
  await page.route(`**${DEMO_PAGE}`, async (route) => {
    const response = await route.fetch();
    const body = (await response.text()).replace(
      "</body>",
      "<script>parent.postMessage('demo-script-ran','*')</script></body>",
    );
    const headers = response.headers();
    // Sabotage runs only: the response without its sandbox.
    if (process.env.DEMO_SABOTAGE_NO_SANDBOX === "1")
      delete headers["content-security-policy"];
    await route.fulfill({ response, body, headers });
  });
  await page.goto("/workspace/chats/new");
  const ran = await page.evaluate(async (src) => {
    const got = new Promise((r) =>
      window.addEventListener(
        "message",
        (e) => e.data === "demo-script-ran" && r(true),
      ),
    );
    const f = document.createElement("iframe");
    f.src = src; // no sandbox attribute: only the response's CSP stands
    document.body.appendChild(f);
    return Promise.race([
      got,
      new Promise((r) => setTimeout(() => r(false), 3000)),
    ]);
  }, DEMO_PAGE);
  expect(ran).toBe(false);
});

test("a demo thread reached by client-side navigation shows its file previews", async ({
  page,
}) => {
  const msgs: string[] = [];
  page.on("console", (m) => msgs.push(m.text()));
  const loaded: string[] = [];
  page.on("response", (r) => {
    if (
      r.url().includes("/mock/api/threads/") &&
      r.request().resourceType() === "document"
    )
      loaded.push(`${r.status()} ${r.url()}`);
  });
  await page.goto("/workspace/chats/new");
  // A client-side move: the page (and its policy) stay; the route changes.
  await page.evaluate((id) => {
    (
      window as unknown as { next: { router: { push(u: string): void } } }
    ).next.router.push(`/workspace/chats/${id}?mock=true`);
  }, DEMO);
  await page.waitForURL(`**/workspace/chats/${DEMO}?mock=true`);
  await page.evaluate((src) => {
    const f = document.createElement("iframe");
    f.src = src;
    document.body.appendChild(f);
  }, DEMO_PAGE);
  await expect.poll(() => loaded.length).toBeGreaterThan(0);
  expect(loaded[0]).toMatch(/^200 /);
  expect(msgs.filter((m) => m.includes("frame-src"))).toEqual([]);
});

test("a demo thread's file opens in its panel after a client-side move", async ({
  page,
}) => {
  const msgs: string[] = [];
  page.on("console", (m) => msgs.push(m.text()));
  const image = "21cfea46-34bd-4aa6-9e1f-3009452fbeb9";
  if (process.env.FRAME_SABOTAGE_NO_MOCK === "1") {
    // Sabotage runs only: the page policy of the fourth round (no mock path
    // unless the page itself was loaded with ?mock=true).
    await page.route("**/workspace/chats/new", async (route) => {
      const response = await route.fetch();
      const headers = response.headers();
      headers["content-security-policy"] = (
        headers["content-security-policy"] ?? ""
      ).replace(/ \S*\/mock\/api\/threads\//, "");
      await route.fulfill({ response, headers });
    });
  }
  await page.goto("/workspace/chats/new");
  await page.evaluate((id) => {
    (
      window as unknown as { next: { router: { push(u: string): void } } }
    ).next.router.push(`/workspace/chats/${id}?mock=true`);
  }, image);
  await page.waitForURL(`**/workspace/chats/${image}?mock=true`);
  const served = page.waitForResponse((r) =>
    r
      .url()
      .includes(
        `/mock/api/threads/${image}/artifacts/mnt/user-data/outputs/doraemon-moe-comic.jpg`,
      ),
  );
  await page.getByRole("button", { name: "Artifacts", exact: true }).click();
  await page
    .getByTestId("artifacts")
    .getByText("doraemon-moe-comic.jpg")
    .click();
  expect((await served).status()).toBe(200);
  await page.waitForTimeout(500);
  expect(msgs.filter((m) => m.includes("frame-src"))).toEqual([]);
});
