import { expect, test, type Page } from "@playwright/test";

import { IDS, installFakeStore } from "./artifacts/fake-store";

/**
 * Spec 012 FR-015: mermaid draws ONLY in the isolated frame
 * (core/artifacts/mermaid.ts, src/app/mermaid-frame/[file]/route.ts).
 *
 * - While a diagram is drawn, the app's own document gets none of mermaid's
 *   nodes (a MutationObserver on the host document), and no request of any
 *   kind is caused by diagram content (a request log).
 * - The frame itself, fed diagram CSS that would fetch from the app with
 *   the owner's cookies, makes no request: it is an opaque origin whose
 *   policy loads nothing.
 * - Every supported diagram type draws from a minimal sample, in the frame,
 *   and passes the SVG allowlist (an <img> appears only then).
 */

test.use({
  timezoneId: "UTC",
  launchOptions: {
    executablePath: process.env.CHROMIUM_EXECUTABLE ?? undefined,
  },
});

/** The reviewer's payloads: diagram CSS that fetches from the app. */
const PAYLOADS = [
  "stateDiagram-v2\nA-->B\nclassDef x fill:red,background:url(/api/b63)\nclass A x",
  "classDiagram\nclass A\nstyle A fill:#f00,background:url(/api/logout?x=1)",
  "block-beta\na\nstyle a fill:#f00,background:url(/api/b65)",
  "flowchart TD\nA-->B\nclassDef x fill:red;}@font-face{font-family:q;src:url(/api/b73)}text{font-family:q\nclass A x",
];
const HTML_LABEL =
  'graph TD\n  A["Start <img src=/api/b80 onerror=window.__canary=1>"] --> B[Done]';

export const SAMPLES: Record<string, string> = {
  flowchart: "flowchart TD\n  A[Start] --> B{Ok?}\n  B -->|yes| C[End]",
  sequence: "sequenceDiagram\n  Alice->>Bob: Hi\n  Bob-->>Alice: Hello",
  class:
    "classDiagram\n  class Animal {\n    +String name\n  }\n  Animal <|-- Dog",
  state: "stateDiagram-v2\n  [*] --> Still\n  Still --> [*]",
  er: "erDiagram\n  CUSTOMER ||--o{ ORDER : places",
  gantt:
    "gantt\n  title Plan\n  dateFormat YYYY-MM-DD\n  section A\n  Task one :a1, 2026-01-01, 3d",
  pie: 'pie title Pets\n  "Dogs" : 3\n  "Cats" : 2',
  mindmap: "mindmap\n  root((Plan))\n    A\n    B",
  timeline: "timeline\n  title History\n  2024 : One\n  2025 : Two",
  sankey: "sankey-beta\n\nA,B,10\nB,C,5",
  xychart:
    'xychart-beta\n  title "Sales"\n  x-axis [a, b, c]\n  y-axis "N" 0 --> 10\n  bar [3, 5, 7]',
  block: "block-beta\n  columns 2\n  a b",
  kanban: "kanban\n  Todo\n    [Write]\n  Done\n    [Read]",
  architecture:
    "architecture-beta\n  group api(cloud)[API]\n  service db(database)[DB] in api\n  service server(server)[Server] in api\n  db:L -- R:server",
  quadrant:
    "quadrantChart\n  title Reach\n  x-axis Low --> High\n  y-axis Low --> High\n  A: [0.3, 0.6]",
  requirement:
    "requirementDiagram\n  requirement r1 {\n    id: 1\n    text: the text\n    risk: high\n    verifymethod: test\n  }\n  element e1 {\n    type: simulation\n  }\n  e1 - satisfies -> r1",
  git: "gitGraph\n  commit\n  branch dev\n  commit\n  checkout main\n  merge dev",
  c4: 'C4Context\n  Person(a, "User")\n  System(b, "System")\n  Rel(a, b, "Uses")',
  packet: 'packet-beta\n  0-15: "Source"\n  16-31: "Dest"',
  radar: "radar-beta\n  axis a, b, c\n  curve x{1, 2, 3}",
  treemap: 'treemap-beta\n"Root"\n    "A": 10\n    "B": 20',
};

const idOf = (name: string) => `Mmd_${name}`.padEnd(22, "0").slice(0, 22);
const PAYLOAD_IDS = PAYLOADS.map((_, i) => `MmdPayload${i}`.padEnd(22, "0"));
const LABEL_ID = "MmdHtmlLabel".padEnd(22, "0");

const FRAME_FILES = /^\/mermaid-frame\/(frame\.html|mermaid\.js|drawer\.js)$/;

/** Requests that reached the network (a load the page or frame policy
 * blocks never does): any request from a frame other than the app's own
 * page, and any request to a path a diagram payload names. */
const PAYLOAD_PATH = /^\/api\/(b6\d|b7\d|b80|logout)/;
function requestLog(page: Page) {
  const log: string[] = [];
  page.on("response", (res) => {
    const req = res.request();
    const url = new URL(req.url());
    if (!/^https?:$/.test(url.protocol)) return;
    const path = url.host === "127.0.0.1:3000" ? url.pathname : req.url();
    const fromFrame = req.frame() !== page.mainFrame();
    if (PAYLOAD_PATH.test(path) || (fromFrame && !FRAME_FILES.test(path))) {
      log.push(path);
    }
  });
  return log;
}

/** From document start on every navigation: every element added to the
 * app's document, and whether it is one of the app's own SVG drawings. */
async function watchHost(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as {
      __added: {
        tag: string;
        id: string;
        cls: string;
        ok: boolean;
        mermaid: boolean;
      }[];
    };
    w.__added = [];
    new MutationObserver((records) => {
      for (const r of records) {
        for (const n of Array.from(r.addedNodes)) {
          if (!(n instanceof Element)) continue;
          for (const e of [n, ...Array.from(n.querySelectorAll("*"))]) {
            w.__added.push({
              tag: e.tagName.toLowerCase(),
              id: e.id,
              cls: String(e.getAttribute("class") ?? ""),
              mermaid:
                e.hasAttribute("aria-roledescription") ||
                /mmd|mermaid/i.test(e.id),
              // The app's own icons, chart and code viewer draw SVG too.
              ok:
                e.closest(
                  "svg.lucide, [data-testid=artifact-chart], .cm-editor, head",
                ) !== null,
            });
          }
        }
      }
    }).observe(document, { childList: true, subtree: true });
  });
}

async function mermaidNodesInHost(page: Page) {
  return page.evaluate(() => {
    const w = window as unknown as {
      __added: {
        tag: string;
        id: string;
        cls: string;
        ok: boolean;
        mermaid: boolean;
      }[];
    };
    return w.__added.filter(
      (a) =>
        (a.tag === "style" && !a.ok) ||
        a.tag === "foreignobject" ||
        a.mermaid ||
        /katex|mermaid/i.test(a.cls),
    );
  });
}

test("drawing a diagram adds none of mermaid's nodes to the app's document and requests nothing", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await installFakeStore(page, {
    mermaid: Object.fromEntries([
      ...PAYLOADS.map((p, i) => [PAYLOAD_IDS[i]!, p]),
      [LABEL_ID, HTML_LABEL],
    ]),
  });
  const log = requestLog(page);
  await watchHost(page);
  // The HTML-label one and each payload, then a clean diagram.
  for (const id of [LABEL_ID, ...PAYLOAD_IDS, IDS.mermaid]) {
    await page.goto(`/workspace/artifacts/${id}`);
    await expect(
      page.locator(
        "[data-testid=artifact-mermaid], [data-testid=mermaid-failed]",
      ),
    ).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(300);
    expect(await mermaidNodesInHost(page), id).toEqual([]);
  }
  // The clean one drew, as an image: the frame really drew in this run.
  await expect(page.getByTestId("artifact-mermaid")).toHaveAttribute(
    "src",
    /^data:image\/svg\+xml;base64,/,
  );
  const frame = page.getByTestId("mermaid-frame");
  await expect(frame).toHaveAttribute("sandbox", "allow-scripts");
  expect(log).toEqual([]);
  expect(
    await page.evaluate(
      () => (window as unknown as { __canary?: number }).__canary,
    ),
  ).toBeUndefined();
});

test("the frame, fed CSS that fetches from the app, fetches nothing (its own policy, opaque origin)", async ({
  page,
}) => {
  await installFakeStore(page, { empty: true });
  await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
  const log = requestLog(page);
  const answers = await page.evaluate(
    async (sources) => {
      const f = document.createElement("iframe");
      f.setAttribute("sandbox", "allow-scripts");
      f.style.cssText =
        "position:fixed;left:-20000px;top:0;width:1200px;height:900px;border:0";
      const port = await new Promise<MessagePort>((resolve) => {
        window.addEventListener("message", (e) => {
          const d = e.data as { type?: string } | null;
          if (e.source !== f.contentWindow || d?.type !== "omni-mermaid-ready")
            return;
          const ch = new MessageChannel();
          f.contentWindow!.postMessage({ type: "omni-mermaid-port" }, "*", [
            ch.port2,
          ]);
          resolve(ch.port1);
        });
        f.src = "/mermaid-frame/frame.html";
        document.body.appendChild(f);
      });
      const out: (boolean | string)[] = [];
      let id = 0;
      for (const source of sources) {
        out.push(
          await new Promise<boolean | string>((resolve) => {
            const mine = ++id;
            port.onmessage = (e) => {
              const d = e.data as { id: number; ok: boolean };
              if (d.id === mine) resolve(d.ok);
            };
            port.postMessage({ id: mine, source, dark: false });
            setTimeout(() => resolve("timeout"), 10_000);
          }),
        );
      }
      await new Promise((r) => setTimeout(r, 800));
      return out;
    },
    [...PAYLOADS, HTML_LABEL],
  );
  // Mermaid drew them (the CSS was live in the frame) ...
  expect(answers.filter((a) => a === true).length).toBeGreaterThan(0);
  // ... and nothing was fetched because of it.
  expect(log).toEqual([]);
  // The policy that stops it, as served.
  const response = await page.request.get("/mermaid-frame/frame.html");
  const csp = response.headers()["content-security-policy"] ?? "";
  expect(csp).toContain("default-src 'none'");
  expect(csp).toContain("connect-src 'none'");
  expect(csp).toContain("font-src 'none'");
  expect(csp).toContain("img-src data:");
});

test("every supported diagram type draws in the isolated frame and passes the allowlist", async ({
  page,
}) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1280, height: 900 });
  await installFakeStore(page, {
    mermaid: Object.fromEntries(
      Object.entries(SAMPLES).map(([k, v]) => [idOf(k), v]),
    ),
  });
  const failed: string[] = [];
  for (const name of Object.keys(SAMPLES)) {
    await page.goto(`/workspace/artifacts/${idOf(name)}`);
    const done = page.locator(
      "[data-testid=artifact-mermaid], [data-testid=mermaid-failed]",
    );
    await expect(done).toBeVisible({ timeout: 20_000 });
    if ((await page.getByTestId("artifact-mermaid").count()) === 0) {
      failed.push(name);
    }
  }
  expect(failed).toEqual([]);
});

test("journey is not supported: it says so and shows the source", async ({
  page,
}) => {
  const id = "MmdJourney".padEnd(22, "0");
  await installFakeStore(page, {
    mermaid: { [id]: "journey\n  title Day\n  section Work\n  Code: 5: Me" },
  });
  await page.goto(`/workspace/artifacts/${id}`);
  await expect(page.getByTestId("mermaid-failed")).toContainText(
    "Journey diagrams aren’t supported",
    { timeout: 20_000 },
  );
});
