import { readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ArtifactChart } from "@/components/workspace/artifacts/store/artifact-chart";
import { parseChartSpec } from "@/core/artifacts/chart-spec";
import {
  downsample,
  FULL_POINTS,
  PREVIEW_POINTS,
} from "@/core/artifacts/chart-spec";
import {
  drawMermaid,
  mermaidConfig,
  prefilter,
} from "@/core/artifacts/mermaid";
import { ArtifactsApiError, readResponse } from "@/core/artifacts/store-api";
import {
  confirmText,
  artifactBindingOf,
  artifactBindingsOf,
  lineageWords,
  panelKey,
  parsePanelKey,
  previewMarkdown,
  refusalWords,
  titleText,
} from "@/core/artifacts/store-logic";
import { legacySelection } from "@/core/studio/tool-select";

/**
 * Spec 012 Slice 1 (frontend): the card binding from a tool message, the
 * chart renderer from data specs (hostile labels included), the mermaid
 * isolation and its fallback, the stale-base refusal, and the source gate
 * (FR-013: no raw-HTML sink under the artifact components or the store).
 */

const ID = "Qm3x9V2kPz8aLr0tYw4bNc";
const tool = (artifact: unknown) => ({
  type: "tool",
  tool_call_id: "call_a",
  content: "Created markdown artifact.",
  artifact,
});

describe("the card from a tool message", () => {
  it("binds exactly the omni_artifact field", () => {
    expect(
      artifactBindingOf(
        tool({
          type: "omni_artifact",
          artifact_id: ID,
          version: 2,
          kind: "chart",
        }),
      ),
    ).toEqual({ artifactId: ID, version: 2, kind: "chart" });
  });

  it("a refused call, another tool's artifact or a malformed field is no card", () => {
    for (const a of [
      null,
      undefined,
      "omni_artifact",
      [],
      { type: "other", artifact_id: ID, version: 1, kind: "markdown" },
      {
        type: "omni_artifact",
        artifact_id: "../x",
        version: 1,
        kind: "markdown",
      },
      { type: "omni_artifact", artifact_id: ID, version: 0, kind: "markdown" },
      {
        type: "omni_artifact",
        artifact_id: ID,
        version: 1.5,
        kind: "markdown",
      },
      { type: "omni_artifact", artifact_id: ID, version: 1, kind: "html" },
      { type: "omni_artifact", artifact_id: ID, version: "1", kind: "code" },
    ]) {
      expect(artifactBindingOf(tool(a))).toBeNull();
    }
    // Only a tool message carries a card.
    expect(
      artifactBindingOf({
        type: "ai",
        artifact: {
          type: "omni_artifact",
          artifact_id: ID,
          version: 1,
          kind: "markdown",
        },
      }),
    ).toBeNull();
  });

  it("one card per result, in order; the panel key round-trips and rejects junk", () => {
    const a = { type: "omni_artifact", artifact_id: ID, kind: "markdown" };
    expect(
      artifactBindingsOf([
        tool({ ...a, version: 1 }),
        { type: "ai", content: "x" },
        tool({ ...a, version: 2 }),
      ]).map((b) => b.version),
    ).toEqual([1, 2]);
    expect(parsePanelKey(panelKey(ID, 3))).toEqual({ id: ID, version: 3 });
    expect(parsePanelKey("/mnt/user-data/outputs/a.md")).toBeNull();
    expect(parsePanelKey("omni-artifact:../../x@1")).toBeNull();
  });

  it("titles and lineage sources are text: control and bidi characters go", () => {
    expect(titleText("Brief‮\u0000\nplan")).toBe("Brief plan");
    expect(titleText("")).toBe("Untitled");
    expect(lineageWords("user", null)).toBeNull();
    expect(lineageWords("content", "web_fetch​")).toBe(
      "Made from content the assistant read (web_fetch)",
    );
  });
});

const HOSTILE = '<script>window.__canary=1</script><img src=x onerror="x()">';
const chartSpec = (over: Record<string, unknown> = {}) => ({
  schema: "omni-chart/1",
  type: "bar",
  title: `CI ${HOSTILE}`,
  x: { field: "day", type: "category", label: `Day ${HOSTILE}` },
  series: [
    { field: "pass", label: `Pass ${HOSTILE}` },
    { field: "fail", label: "Fail" },
  ],
  data: [
    { day: `Mon ${HOSTILE}`, pass: 3, fail: 1 },
    { day: "Tue", pass: null, fail: 2 },
    { day: "Wed", pass: 5, fail: 0 },
  ],
  units: "runs",
  ...over,
});

const ALLOWED = new Set([
  "figure",
  "figcaption",
  "svg",
  "title",
  "g",
  "line",
  "text",
  "rect",
  "circle",
  "path",
  "ul",
  "li",
  "span",
]);

function renderChart(raw: unknown, compact = false): string {
  const parsed = parseChartSpec(raw);
  if (!parsed.ok) throw new Error(parsed.reason);
  return renderToStaticMarkup(
    createElement(ArtifactChart, { spec: parsed.spec, compact }),
  );
}

function attrNames(html: string): string[] {
  return [...html.matchAll(/<[a-zA-Z][^>]*>/g)].flatMap((tag) =>
    [...tag[0].matchAll(/\s([a-zA-Z_:][-a-zA-Z0-9_:.]*)="[^"]*"/g)].map(
      (m) => m[1]!,
    ),
  );
}

function tags(html: string): string[] {
  return [...html.matchAll(/<([a-zA-Z][a-zA-Z0-9-]*)/g)].map((m) => m[1]!);
}

describe("the chart renderer (omni-chart/1)", () => {
  for (const type of ["bar", "line", "area", "scatter", "pie", "donut"]) {
    it(`${type}: React SVG elements only; hostile labels stay text`, () => {
      const spec =
        type === "pie" || type === "donut"
          ? chartSpec({ type, series: [{ field: "pass", label: "Pass" }] })
          : type === "scatter"
            ? chartSpec({
                type,
                x: { field: "n", type: "number" },
                data: [
                  { n: 1, pass: 2, fail: 1 },
                  { n: 4, pass: 3, fail: null },
                ],
              })
            : chartSpec({ type });
      const html = renderChart(spec);
      expect(new Set(tags(html))).toEqual(
        new Set([...tags(html)].filter((t) => ALLOWED.has(t))),
      );
      // No event attribute on any element (escaped text in a value is fine).
      expect(attrNames(html).filter((n) => /^on/i.test(n))).toEqual([]);
      expect(html).toContain("&lt;script&gt;");
      expect(html).toContain('data-chart-type="' + type + '"');
      // Every mark carries a tooltip as a <title> element.
      expect(html).toMatch(/<title>[^<]+<\/title>/);
    });
  }

  it("`stacked` is read for bar and area, refused elsewhere or when not a boolean", () => {
    const bar = parseChartSpec(chartSpec({ type: "bar", stacked: true }));
    expect(bar.ok && bar.spec.stacked).toBe(true);
    const area = parseChartSpec(chartSpec({ type: "area", stacked: true }));
    expect(area.ok && area.spec.stacked).toBe(true);
    expect(parseChartSpec(chartSpec({ type: "line", stacked: true })).ok).toBe(
      false,
    );
    expect(parseChartSpec(chartSpec({ type: "bar", stacked: "yes" })).ok).toBe(
      false,
    );
    const off = parseChartSpec(chartSpec({ type: "bar" }));
    expect(off.ok && off.spec.stacked).toBeFalsy();
  });

  it("a time axis and a legend", () => {
    const html = renderChart(
      chartSpec({
        x: { field: "day", type: "time" },
        data: [
          { day: "2026-11-10", pass: 3, fail: 1 },
          { day: "2026-11-11", pass: 4, fail: 2 },
        ],
      }),
    );
    expect(html).toContain('data-testid="artifact-chart-legend"');
    expect(html).toContain("2026-11-10");
    expect(html).toContain("var(--artifact-series-2)");
  });

  it("rows are read by their own keys: __proto__ and constructor are just names", () => {
    const raw = JSON.parse(
      '{"type":"bar","title":"Proto","x":{"field":"__proto__","type":"category"},' +
        '"series":[{"field":"constructor","label":"C"}],' +
        '"data":[{"__proto__":"a","constructor":2}]}',
    ) as unknown;
    // JSON.parse makes __proto__ an own key, as the gateway's JSON does.
    const parsed = parseChartSpec(raw);
    expect(parsed.ok).toBe(true);
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
    const html = renderChart(raw);
    expect(html).toContain(">a<");
  });

  it("refuses what is not data: callbacks, bad types, oversized, control characters", () => {
    expect(parseChartSpec(chartSpec({ type: "radar" })).ok).toBe(false);
    expect(parseChartSpec(chartSpec({ title: "x\u0007" })).ok).toBe(false);
    expect(
      parseChartSpec(
        chartSpec({ data: [{ day: "Mon", pass: "=cmd()", fail: 1 }] }),
      ).ok,
    ).toBe(false);
    expect(
      parseChartSpec(chartSpec({ data: [{ day: "Mon", pass: () => 1 }] })).ok,
    ).toBe(false);
    expect(parseChartSpec("{not json").ok).toBe(false);
    expect(
      parseChartSpec(
        chartSpec({ type: "pie" }), // two series
      ).ok,
    ).toBe(false);
  });
});

describe("mermaid: drawn in the isolated frame, shown as an image, or the source", () => {
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg"><g><text>A</text></g></svg>';
  const deps = (render: (s: string, d: boolean) => Promise<string>) => ({
    render,
    check: (s: string) =>
      s.includes("foreignObject")
        ? ({ ok: false, reason: "the element <foreignObject>" } as const)
        : ({ ok: true } as const),
    toUrl: (s: string) => `data:image/svg+xml;base64,${btoa(s)}`,
  });

  it("strict, HTML labels off, page-styling directives locked", () => {
    const c = mermaidConfig(false);
    expect(c.securityLevel).toBe("strict");
    expect(c.htmlLabels).toBe(false);
    expect((c.flowchart as { htmlLabels: boolean }).htmlLabels).toBe(false);
    for (const key of [
      "securityLevel",
      "htmlLabels",
      "secure",
      "dompurifyConfig",
      "themeCSS",
      "fontFamily",
    ]) {
      expect(c.secure).toContain(key);
    }
  });

  it("a drawing that passes the allowlist becomes an image URL", async () => {
    const render = vi.fn(() => Promise.resolve(svg));
    const r = await drawMermaid("graph TD; A-->B", true, deps(render));
    expect(r).toEqual({
      ok: true,
      url: `data:image/svg+xml;base64,${btoa(svg)}`,
      linksRemoved: false,
    });
    expect(render).toHaveBeenCalledWith("graph TD; A-->B", true);
  });

  it("the frame failing or an allowlist failure falls back", async () => {
    expect(
      (
        await drawMermaid(
          "graph TD; A-->",
          false,
          deps(() => Promise.reject(new Error("parse"))),
        )
      ).ok,
    ).toBe(false);
    expect(
      await drawMermaid(
        "graph TD; A-->B",
        false,
        deps(() => Promise.resolve("<svg><foreignObject/></svg>")),
      ),
    ).toEqual({ ok: false, reason: "the element <foreignObject>" });
  });

  // The reviewer's payloads: diagram CSS that would fetch from the app.
  it.each([
    [
      "stateDiagram-v2\nA-->B\nclassDef x fill:red,background:url(/api/b63)\nclass A x",
    ],
    [
      "classDiagram\nclass A\nstyle A fill:#f00,background:url(/api/logout?x=1)",
    ],
    ["block-beta\na\nstyle a fill:#f00,background:url(/api/b65)"],
    [
      "graph TD\nA-->B\nclassDef x fill:red;}@font-face{font-family:q;src:url(/api/b73)}text{font-family:q\nclass A x",
    ],
    ['graph TD\nA-->B\nstyle A fill:image-set("x.png" 1x)'],
    ["graph TD\nA-->B\nclassDef x fill:red\\;color:blue"],
    ["graph TD\nA-->B\nlinkStyle 0 stroke:red}"],
    ['%%{init: {"securityLevel": "loose"}}%%\ngraph TD; A-->B'],
  ])("is refused before the frame sees it: %s", async (source) => {
    const render = vi.fn(() => Promise.resolve(svg));
    expect((await drawMermaid(source, false, deps(render))).ok).toBe(false);
    expect(render).not.toHaveBeenCalled();
  });

  it("click, link, callback and href statements are removed, and said so", async () => {
    const pre = prefilter(
      'graph TD\nA-->B\nclick A "https://evil.example"\n  link A "x"\ncallback A fn\nlinkStyle 0 stroke:red',
    );
    expect(pre).toEqual({
      source: "graph TD\nA-->B\nlinkStyle 0 stroke:red",
      linksRemoved: true,
    });
    const render = vi.fn(() => Promise.resolve(svg));
    const r = await drawMermaid(
      'graph TD\nA-->B\nclick A "x"',
      false,
      deps(render),
    );
    expect(r.ok && r.linksRemoved).toBe(true);
    expect(render).toHaveBeenCalledWith("graph TD\nA-->B", false);
  });
});

describe("raw titles for rename and typed delete", () => {
  it("NFKC, invisible and control characters removed, not defanged", () => {
    expect(confirmText("brief.md \u200bplan\u202e")).toBe("brief.md plan");
    expect(confirmText("ｆｕｌｌ\u00a0width")).toBe("full width");
    expect(confirmText("evil.com")).toBe("evil.com");
  });
});

describe("chart caps", () => {
  it("previews draw at most 200 points per series; values are clamped", () => {
    const rows = Array.from({ length: 5000 }, (_, i) => ({ n: i, v: i }));
    const parsed = parseChartSpec({
      type: "line",
      title: "Big",
      x: { field: "n", type: "number" },
      series: [{ field: "v", label: "V" }],
      data: rows,
    });
    if (!parsed.ok) throw new Error(parsed.reason);
    expect(downsample(parsed.spec.rows, PREVIEW_POINTS)).toHaveLength(200);
    expect(downsample(parsed.spec.rows, FULL_POINTS)).toHaveLength(1000);
    const html = renderToStaticMarkup(
      createElement(ArtifactChart, { spec: parsed.spec, compact: true }),
    );
    expect(html.match(/<path /g)?.length ?? 0).toBeLessThanOrEqual(2);
    const full = renderToStaticMarkup(
      createElement(ArtifactChart, { spec: parsed.spec }),
    );
    expect(full).toContain("Showing 1,000 of 5,000 points");
    const huge = parseChartSpec({
      type: "bar",
      title: "Huge",
      x: { field: "c", type: "category" },
      series: [{ field: "v", label: "V" }],
      data: [
        { c: "a", v: 1e308 },
        { c: "b", v: -1e308 },
      ],
    });
    if (!huge.ok) throw new Error(huge.reason);
    const hugeHtml = renderToStaticMarkup(
      createElement(ArtifactChart, { spec: huge.spec }),
    );
    expect(hugeHtml).not.toMatch(/NaN|Infinity/);
  });
});

describe("a stale base version", () => {
  it("is a refusal with its code and the current version, worded for the owner", async () => {
    const res = new Response(
      JSON.stringify({
        detail: {
          code: "stale_base_version",
          message: "This artifact changed: the latest version is 4.",
          current_version: 4,
        },
      }),
      { status: 409, headers: { "Content-Type": "application/json" } },
    );
    const err = await readResponse(res).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ArtifactsApiError);
    const e = err as ArtifactsApiError;
    expect(e.code).toBe("stale_base_version");
    expect(e.extra.current_version).toBe(4);
    expect(refusalWords(e)).toBe("A newer version exists.");
  });
});

describe("Studio: Artifacts is opt-in", () => {
  it("a legacy agent (no allowlist) shows Artifacts unticked", () => {
    const sel = legacySelection(null, {
      integrations: [
        {
          id: "builtin:artifacts",
          name: "Artifacts",
          kind: "builtin",
          status: "connected",
          detail: "",
          tools: [
            { name: "artifact_create", description: "", tier: 2 },
          ] as never,
        },
      ],
    } as never);
    expect(sel).toEqual({});
  });
});

// FR-013 source gate: no raw-HTML sink in the artifact components, the
// store pages or the artifact core.
const SRC = join(__dirname, "..", "..", "src");
const GATED = [
  "components/workspace/artifacts",
  "app/workspace/artifacts",
  "core/artifacts",
];
const ALLOWLIST: string[] = [];
const SINK =
  /dangerouslySetInnerHTML|\.innerHTML\b|\.outerHTML\b|insertAdjacentHTML|document\.write|createContextualFragment|srcdoc/;

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory()
      ? walk(p)
      : /\.(ts|tsx)$/.test(n)
        ? [p]
        : [];
  });
}

describe("FR-013 source gate", () => {
  it("no new HTML sink under the artifact components, pages or core", () => {
    const hits = GATED.flatMap((d) => walk(join(SRC, d)))
      .filter((f) => !ALLOWLIST.some((a) => f.endsWith(a)))
      .filter((f) => SINK.test(readFileSync(f, "utf8")));
    expect(hits).toEqual([]);
  });
});

describe("imported files and markdown previews (S1 follow-ups)", () => {
  it("a chat's output file says so, not the content badge", () => {
    expect(lineageWords("import", "a file from this chat")).toBe(
      "Imported from its chat",
    );
    // Older imports were recorded as content with the importer's source.
    expect(lineageWords("content", "a file from the chat")).toBe(
      "Imported from its chat",
    );
    expect(lineageWords("content", "web_fetch")).toContain(
      "content the assistant read",
    );
  });

  it("a card preview clips only at a block boundary", () => {
    const doc =
      "# Brief\n\nSome **bold\nstill bold** here.\n" +
      "x".repeat(380) +
      "\n\nplain text after";
    const out = previewMarkdown(doc, 6, 400);
    expect(out).toBe("# Brief");
    const short = "# Brief\n\nplain text after";
    expect(previewMarkdown(short)).toBe(short);
    const setext =
      "Title\n\nline one\nline two\nline three\nline four\nline five\n---";
    expect(previewMarkdown(setext, 6, 400).endsWith("---")).toBe(false);
    const fence = "```\n" + "code\n".repeat(10);
    expect(previewMarkdown(fence, 6, 400).trimEnd().endsWith("```")).toBe(true);
  });
});
