/**
 * Spec 012 FR-024: the `omni-chart/1` data spec, checked again on the client
 * (the gateway validates on write; this side never trusts that it did).
 *
 * Rows are read into Maps of their OWN keys only: a row is never merged into
 * a plain object by key, so `__proto__`, `constructor` or `prototype` in the
 * data are just names (never the prototype chain).
 */

export type ChartType = "bar" | "line" | "area" | "scatter" | "pie" | "donut";
export type Cell = string | number | boolean | null;
export type Row = Map<string, Cell>;

export interface ChartSpec {
  type: ChartType;
  title: string;
  x: { field: string; type: "category" | "time" | "number"; label?: string };
  series: { field: string; label: string }[];
  rows: Row[];
  units?: string;
  /** Stacks bar and area series. NOT read from content: the gateway's
   * omni-chart/1 schema has no such key yet (a follow-up there). */
  stacked?: boolean;
}

const TYPES = new Set(["bar", "line", "area", "scatter", "pie", "donut"]);
const X_TYPES = new Set(["category", "time", "number"]);
const CONTROL = /[\p{Cc}]/u;
const MAX_ROWS = 5000;
const MAX_SERIES = 8;

type Result = { ok: true; spec: ChartSpec } | { ok: false; reason: string };
const fail = (reason: string): Result => ({ ok: false, reason });

function isRecord(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

function own(obj: Record<string, unknown>, key: string): unknown {
  return Object.prototype.hasOwnProperty.call(obj, key) ? obj[key] : undefined;
}

function text(v: unknown, max: number): string | null {
  if (typeof v !== "string" || v.length > max || CONTROL.test(v)) return null;
  return v;
}

/** Parse a chart artifact's content (object, or its JSON string). */
export function parseChartSpec(raw: unknown): Result {
  let value = raw;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value) as unknown;
    } catch {
      return fail("not JSON");
    }
  }
  if (!isRecord(value)) return fail("not an object");
  const type = own(value, "type");
  if (typeof type !== "string" || !TYPES.has(type)) return fail("bad type");
  const title = text(own(value, "title"), 200);
  if (!title) return fail("bad title");
  const xRaw = own(value, "x");
  if (!isRecord(xRaw)) return fail("bad x");
  const xField = text(own(xRaw, "field"), 64);
  const xType = own(xRaw, "type");
  if (!xField || typeof xType !== "string" || !X_TYPES.has(xType))
    return fail("bad x");
  const xLabelRaw = own(xRaw, "label");
  const xLabel =
    xLabelRaw === undefined || xLabelRaw === null
      ? undefined
      : text(xLabelRaw, 80);
  if (xLabel === null) return fail("bad x label");

  const seriesRaw = own(value, "series");
  if (
    !Array.isArray(seriesRaw) ||
    seriesRaw.length < 1 ||
    seriesRaw.length > MAX_SERIES
  ) {
    return fail("bad series");
  }
  const series: ChartSpec["series"] = [];
  const seen = new Set<string>();
  for (const s of seriesRaw) {
    if (!isRecord(s)) return fail("bad series");
    const field = text(own(s, "field"), 64);
    const label = text(own(s, "label"), 80);
    if (!field || !label || seen.has(field) || field === xField)
      return fail("bad series");
    seen.add(field);
    series.push({ field, label });
  }
  if ((type === "pie" || type === "donut") && series.length !== 1)
    return fail("pie takes one series");

  const dataRaw = own(value, "data");
  if (
    !Array.isArray(dataRaw) ||
    dataRaw.length < 1 ||
    dataRaw.length > MAX_ROWS
  )
    return fail("bad data");
  const rows: Row[] = [];
  for (const r of dataRaw) {
    if (!isRecord(r)) return fail("bad row");
    const keys = Object.keys(r);
    if (keys.length > 32) return fail("bad row");
    const row: Row = new Map();
    for (const k of keys) {
      const v = r[k];
      if (
        v === null ||
        typeof v === "boolean" ||
        (typeof v === "number" && Number.isFinite(v))
      ) {
        row.set(k, v);
      } else if (typeof v === "string" && v.length <= 200 && !CONTROL.test(v)) {
        row.set(k, v);
      } else {
        return fail("bad cell");
      }
    }
    if (!row.has(xField)) return fail("row without x");
    const xv = row.get(xField);
    if (xType === "number" && typeof xv !== "number")
      return fail("bad x value");
    if (xType === "time" && (typeof xv !== "string" || isNaN(Date.parse(xv))))
      return fail("bad x value");
    if (
      xType === "category" &&
      typeof xv !== "string" &&
      typeof xv !== "number"
    )
      return fail("bad x value");
    for (const s of series) {
      const sv = row.get(s.field);
      if (sv !== undefined && sv !== null && typeof sv !== "number")
        return fail("series value not a number");
    }
    rows.push(row);
  }
  const unitsRaw = own(value, "units");
  const units =
    unitsRaw === undefined || unitsRaw === null
      ? undefined
      : text(unitsRaw, 40);
  if (units === null) return fail("bad units");
  return {
    ok: true,
    spec: {
      type: type as ChartType,
      title,
      x: {
        field: xField,
        type: xType as ChartSpec["x"]["type"],
        label: xLabel,
      },
      series,
      rows,
      units,
    },
  };
}

/** A series value of a row, or null when missing. */
/** Values are clamped to ±1e15 so a range never overflows to Infinity. */
export const VALUE_LIMIT = 1e15;
export function clampValue(v: number): number {
  return Math.max(-VALUE_LIMIT, Math.min(VALUE_LIMIT, v));
}

export function valueOf(row: Row, field: string): number | null {
  const v = row.get(field);
  return typeof v === "number" && Number.isFinite(v) ? clampValue(v) : null;
}

/** Points drawn per series: cards and the store grid, and the full view. */
export const PREVIEW_POINTS = 200;
export const FULL_POINTS = 1000;

/** Every k-th row (first and last kept) so at most `max` are drawn. */
export function downsample(rows: Row[], max: number): Row[] {
  if (rows.length <= max) return rows;
  const step = (rows.length - 1) / (max - 1);
  const out: Row[] = [];
  for (let i = 0; i < max; i++) out.push(rows[Math.round(i * step)]!);
  return out;
}

/** "Nice" tick values covering [lo, hi]. */
export function niceTicks(lo: number, hi: number, count = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0];
  if (lo === hi) {
    hi = lo === 0 ? 1 : lo + Math.abs(lo);
    if (lo > 0) lo = 0;
  }
  const span = hi - lo;
  const raw = span / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const start = Math.floor(lo / step) * step;
  const end = Math.ceil(hi / step) * step;
  const out: number[] = [];
  for (let v = start; v <= end + step / 2 && out.length < 50; v += step) {
    out.push(Number(v.toPrecision(12)));
  }
  return out;
}

export function formatNumber(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${+(v / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${+(v / 1e6).toFixed(1)}M`;
  if (abs >= 1e4) return `${+(v / 1e3).toFixed(1)}k`;
  if (abs !== 0 && abs < 0.01) return v.toExponential(1);
  return String(+v.toFixed(2));
}
