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
