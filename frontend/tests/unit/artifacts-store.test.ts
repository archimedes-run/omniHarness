import { readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ArtifactChart } from "@/components/workspace/artifacts/store/artifact-chart";
import { parseChartSpec } from "@/core/artifacts/chart-spec";
import {
  drawMermaid,
  mermaidConfig,
  type MermaidLike,
} from "@/core/artifacts/mermaid";
import { ArtifactsApiError, readResponse } from "@/core/artifacts/store-api";
import {
  artifactBindingOf,
  artifactBindingsOf,
  lineageWords,
  panelKey,
  parsePanelKey,
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

  it("stacked bars, a time axis and a legend", () => {
    const html = renderChart(
      chartSpec({
        stacked: true,
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

describe("mermaid: drawn in an isolated step, shown as an image, or the source", () => {
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg"><g><text>A</text></g></svg>';
  const fake = (impl: MermaidLike["render"]) => {
    const m: MermaidLike & { configs: Record<string, unknown>[] } = {
      configs: [],
      initialize(c) {
        m.configs.push(c);
      },
      render: impl,
    };
    return m;
  };

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

  it("a drawing that passes the allowlist becomes an image URL; the container is removed", async () => {
    const m = fake(() => Promise.resolve({ svg }));
    const dispose = vi.fn();
    const r = await drawMermaid("graph TD; A-->B", true, {
      load: () => Promise.resolve(m),
      check: () => ({ ok: true }),
      toUrl: (s) => `data:image/svg+xml;base64,${btoa(s)}`,
      container: () => ({ element: {} as Element, dispose }),
    });
    expect(r).toEqual({
      ok: true,
      url: `data:image/svg+xml;base64,${btoa(svg)}`,
    });
    expect(m.configs[0]!.securityLevel).toBe("strict");
    expect(dispose).toHaveBeenCalledOnce();
  });

  it("mermaid throwing, an allowlist failure or a security directive falls back (and the container still goes)", async () => {
    const dispose = vi.fn();
    const deps = {
      check: (s: string) =>
        s.includes("foreignObject")
          ? ({ ok: false, reason: "the element <foreignObject>" } as const)
          : ({ ok: true } as const),
      toUrl: () => "data:",
      container: () => ({ element: {} as Element, dispose }),
    };
    const throws = await drawMermaid("graph TD; A-->", false, {
      ...deps,
      load: () =>
        Promise.resolve(fake(() => Promise.reject(new Error("parse")))),
    });
    expect(throws.ok).toBe(false);
    const html = await drawMermaid("graph TD; A-->B", false, {
      ...deps,
      load: () =>
        Promise.resolve(
          fake(() => Promise.resolve({ svg: "<svg><foreignObject/></svg>" })),
        ),
    });
    expect(html).toEqual({ ok: false, reason: "the element <foreignObject>" });
    expect(dispose).toHaveBeenCalledTimes(2);
    const load = vi.fn();
    const directive = await drawMermaid(
      '%%{init: {"securityLevel": "loose"}}%%\ngraph TD; A-->B',
      false,
      { ...deps, load },
    );
    expect(directive.ok).toBe(false);
    expect(load).not.toHaveBeenCalled();
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
