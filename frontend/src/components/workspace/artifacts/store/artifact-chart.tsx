"use client";

import { useEffect, useRef, useState } from "react";

import {
  formatNumber,
  niceTicks,
  valueOf,
  type ChartSpec,
  type Row,
} from "@/core/artifacts/chart-spec";
import { safeField } from "@/core/display/safe";
import { cn } from "@/lib/utils";

/**
 * Spec 012 FR-024: an `omni-chart/1` data spec drawn as React SVG elements.
 * No chart library and no HTML strings: every label is a text node (React
 * escapes it) made safe with safeField; tooltips are <title> elements.
 * Colours are the Graphite artifact series tokens (both themes).
 */

const series = (i: number) => `var(--artifact-series-${(i % 8) + 1})`;

function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) setWidth(Math.round(w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

function cellText(v: string | number | boolean | null | undefined): string {
  if (v === null || v === undefined) return "";
  return safeField(String(v));
}

function xText(spec: ChartSpec, row: Row): string {
  const v = row.get(spec.x.field);
  if (spec.x.type === "time" && typeof v === "string") {
    const d = new Date(v);
    if (!isNaN(d.getTime())) {
      return v.length <= 10
        ? d.toISOString().slice(0, 10)
        : d.toISOString().slice(0, 16).replace("T", " ");
    }
  }
  return cellText(v);
}

export function ArtifactChart({
  spec,
  compact = false,
  className,
}: {
  spec: ChartSpec;
  compact?: boolean;
  className?: string;
}) {
  const [ref, measured] = useWidth(compact ? 320 : 640);
  const width = Math.max(200, measured);
  const height = compact
    ? 150
    : Math.round(Math.min(380, Math.max(220, width * 0.55)));
  const title = safeField(spec.title);
  const units = safeField(spec.units);
  const pie = spec.type === "pie" || spec.type === "donut";
  const showLegend = !compact && (pie || spec.series.length > 1);
  const labels = spec.series.map((s) => safeField(s.label));

  return (
    <figure
      ref={ref}
      className={cn("flex w-full min-w-0 flex-col gap-2", className)}
      data-testid="artifact-chart"
      data-chart-type={spec.type}
    >
      {!compact && (
        <figcaption className="text-foreground text-sm font-semibold">
          {title}
        </figcaption>
      )}
      <svg
        role="img"
        aria-label={title}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="text-muted-foreground block h-auto max-w-full"
        fontSize={compact ? 10 : 11}
      >
        <title>{title}</title>
        {pie ? (
          <PieMarks spec={spec} width={width} height={height} units={units} />
        ) : (
          <XYMarks
            spec={spec}
            width={width}
            height={height}
            compact={compact}
            labels={labels}
            units={units}
          />
        )}
      </svg>
      {showLegend && (
        <ul
          className="text-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs"
          data-testid="artifact-chart-legend"
        >
          {(pie ? spec.rows.map((r) => xText(spec, r)) : labels).map(
            (label, i) => (
              <li key={i} className="flex min-w-0 items-center gap-1.5">
                <span
                  aria-hidden
                  className="inline-block size-2.5 shrink-0 rounded-sm"
                  style={{ background: series(i) }}
                />
                <span className="max-w-[16rem] truncate" title={label}>
                  {label}
                </span>
              </li>
            ),
          )}
        </ul>
      )}
    </figure>
  );
}

function XYMarks({
  spec,
  width,
  height,
  compact,
  labels,
  units,
}: {
  spec: ChartSpec;
  width: number;
  height: number;
  compact: boolean;
  labels: string[];
  units: string;
}) {
  const m = compact
    ? { l: 34, r: 8, t: 8, b: 20 }
    : { l: 48, r: 16, t: 10, b: spec.x.label ? 46 : 30 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = Math.max(10, height - m.t - m.b);
  const rows = spec.rows;
  const stacked =
    spec.stacked === true && (spec.type === "bar" || spec.type === "area");

  // y domain (stacked: the sums).
  let lo = 0;
  let hi = 0;
  for (const row of rows) {
    let pos = 0;
    let neg = 0;
    for (const s of spec.series) {
      const v = valueOf(row, s.field);
      if (v === null) continue;
      if (stacked) {
        if (v >= 0) pos += v;
        else neg += v;
      } else {
        lo = Math.min(lo, v);
        hi = Math.max(hi, v);
      }
    }
    if (stacked) {
      lo = Math.min(lo, neg);
      hi = Math.max(hi, pos);
    }
  }
  const ticks = niceTicks(lo, hi, compact ? 3 : 5);
  const y0 = ticks[0]!;
  const y1 = ticks[ticks.length - 1]!;
  const y = (v: number) => m.t + ih - ((v - y0) / (y1 - y0 || 1)) * ih;

  // x positions.
  const band = spec.type === "bar" || spec.x.type === "category";
  let xs: number[];
  let bw = 0;
  if (band) {
    const step = iw / rows.length;
    bw = step * 0.8;
    xs = rows.map((_, i) => m.l + step * i + step / 2);
  } else {
    const raw = rows.map((r) => {
      const v = r.get(spec.x.field);
      return spec.x.type === "time" ? Date.parse(String(v)) : Number(v);
    });
    const min = Math.min(...raw);
    const max = Math.max(...raw);
    xs = raw.map((v) =>
      max === min ? m.l + iw / 2 : m.l + ((v - min) / (max - min)) * iw,
    );
  }
  const maxLabels = Math.max(2, Math.floor(iw / (compact ? 60 : 80)));
  const every = Math.max(1, Math.ceil(rows.length / maxLabels));
  const tip = (row: Row, i: number, v: number) =>
    `${xText(spec, row)}: ${labels[i]} ${formatNumber(v)}${units ? ` ${units}` : ""}`;

  const marks: React.ReactNode[] = [];
  if (spec.type === "bar") {
    const per = stacked ? 1 : spec.series.length;
    const w = bw / per;
    rows.forEach((row, ri) => {
      let pos = 0;
      let neg = 0;
      spec.series.forEach((s, si) => {
        const v = valueOf(row, s.field);
        if (v === null) return;
        let top: number;
        let bottom: number;
        let x: number;
        if (stacked) {
          const from = v >= 0 ? pos : neg;
          const to = from + v;
          if (v >= 0) pos = to;
          else neg = to;
          top = y(Math.max(from, to));
          bottom = y(Math.min(from, to));
          x = xs[ri]! - bw / 2;
        } else {
          top = y(Math.max(0, v));
          bottom = y(Math.min(0, v));
          x = xs[ri]! - bw / 2 + w * si;
        }
        marks.push(
          <rect
            key={`b-${ri}-${si}`}
            x={x}
            y={top}
            width={Math.max(1, w - (per > 1 ? 1 : 0))}
            height={Math.max(0.5, bottom - top)}
            style={{ fill: series(si) }}
            rx={1.5}
          >
            <title>{tip(row, si, v)}</title>
          </rect>,
        );
      });
    });
  } else if (spec.type === "scatter") {
    rows.forEach((row, ri) =>
      spec.series.forEach((s, si) => {
        const v = valueOf(row, s.field);
        if (v === null) return;
        marks.push(
          <circle
            key={`p-${ri}-${si}`}
            cx={xs[ri]}
            cy={y(v)}
            r={compact ? 2.5 : 3.5}
            style={{ fill: series(si) }}
            fillOpacity={0.85}
          >
            <title>{tip(row, si, v)}</title>
          </circle>,
        );
      }),
    );
  } else {
    // line and area (area stacked when asked).
    const base = rows.map(() => 0);
    spec.series.forEach((s, si) => {
      const segments: {
        x: number;
        y: number;
        b: number;
        row: Row;
        v: number;
      }[][] = [[]];
      rows.forEach((row, ri) => {
        const v = valueOf(row, s.field);
        if (v === null) {
          if (segments[segments.length - 1]!.length) segments.push([]);
          return;
        }
        const b = stacked ? base[ri]! : 0;
        const top = stacked ? b + v : v;
        if (stacked) base[ri] = top;
        segments[segments.length - 1]!.push({
          x: xs[ri]!,
          y: y(top),
          b: y(spec.type === "area" ? b : 0),
          row,
          v,
        });
      });
      segments.forEach((seg, gi) => {
        if (!seg.length) return;
        const line = seg
          .map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
          .join("");
        if (spec.type === "area") {
          const back = [...seg]
            .reverse()
            .map((p) => `L${p.x.toFixed(1)},${p.b.toFixed(1)}`)
            .join("");
          marks.push(
            <path
              key={`a-${si}-${gi}`}
              d={`${line}${back}Z`}
              style={{ fill: series(si) }}
              fillOpacity={0.25}
            />,
          );
        }
        marks.push(
          <path
            key={`l-${si}-${gi}`}
            d={line}
            fill="none"
            style={{ stroke: series(si) }}
            strokeWidth={compact ? 1.5 : 2}
            strokeLinejoin="round"
          />,
        );
        if (!compact && rows.length <= 60) {
          seg.forEach((p, pi) =>
            marks.push(
              <circle
                key={`d-${si}-${gi}-${pi}`}
                cx={p.x}
                cy={p.y}
                r={3}
                style={{ fill: series(si) }}
              >
                <title>{tip(p.row, si, p.v)}</title>
              </circle>,
            ),
          );
        }
      });
    });
  }

  return (
    <g>
      {ticks.map((t) => (
        <g key={`t-${t}`}>
          <line
            x1={m.l}
            x2={m.l + iw}
            y1={y(t)}
            y2={y(t)}
            stroke="var(--border)"
            strokeWidth={t === 0 ? 1.25 : 1}
          />
          <text
            x={m.l - 6}
            y={y(t)}
            textAnchor="end"
            dominantBaseline="middle"
            fill="currentColor"
          >
            {formatNumber(t)}
          </text>
        </g>
      ))}
      {rows.map((row, i) =>
        i % every === 0 ? (
          <text
            key={`x-${i}`}
            x={xs[i]}
            y={m.t + ih + (compact ? 13 : 16)}
            textAnchor="middle"
            fill="currentColor"
          >
            {truncate(xText(spec, row), compact ? 8 : 14)}
          </text>
        ) : null,
      )}
      {!compact && spec.x.label && (
        <text
          x={m.l + iw / 2}
          y={height - 6}
          textAnchor="middle"
          fill="currentColor"
        >
          {safeField(spec.x.label)}
        </text>
      )}
      {!compact && units && (
        <text x={4} y={m.t} dominantBaseline="hanging" fill="currentColor">
          {units}
        </text>
      )}
      {marks}
    </g>
  );
}

function truncate(text: string, n: number): string {
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}

function PieMarks({
  spec,
  width,
  height,
  units,
}: {
  spec: ChartSpec;
  width: number;
  height: number;
  units: string;
}) {
  const field = spec.series[0]!.field;
  const parts = spec.rows
    .map((row, i) => ({ row, i, v: valueOf(row, field) ?? 0 }))
    .filter((p) => p.v > 0);
  const total = parts.reduce((s, p) => s + p.v, 0);
  const r = Math.max(10, Math.min(width, height) / 2 - 8);
  const cx = width / 2;
  const cy = height / 2;
  const inner = spec.type === "donut" ? r * 0.58 : 0;
  if (total <= 0) {
    return (
      <text x={cx} y={cy} textAnchor="middle" fill="currentColor">
        No values to draw
      </text>
    );
  }
  let angle = -Math.PI / 2;
  return (
    <g>
      {parts.map((p) => {
        const share = p.v / total;
        const a0 = angle;
        const a1 = angle + share * Math.PI * 2;
        angle = a1;
        const label = `${xText(spec, p.row)}: ${formatNumber(p.v)}${units ? ` ${units}` : ""} (${Math.round(share * 100)}%)`;
        if (share >= 0.9999) {
          return (
            <g key={p.i}>
              <circle cx={cx} cy={cy} r={r} style={{ fill: series(p.i) }}>
                <title>{label}</title>
              </circle>
              {inner > 0 && (
                <circle cx={cx} cy={cy} r={inner} fill="var(--card)" />
              )}
            </g>
          );
        }
        const large = a1 - a0 > Math.PI ? 1 : 0;
        const pt = (rad: number, a: number) =>
          `${(cx + rad * Math.cos(a)).toFixed(2)},${(cy + rad * Math.sin(a)).toFixed(2)}`;
        const d =
          inner > 0
            ? `M${pt(r, a0)}A${r},${r} 0 ${large} 1 ${pt(r, a1)}L${pt(inner, a1)}A${inner},${inner} 0 ${large} 0 ${pt(inner, a0)}Z`
            : `M${cx},${cy}L${pt(r, a0)}A${r},${r} 0 ${large} 1 ${pt(r, a1)}Z`;
        return (
          <path
            key={p.i}
            d={d}
            style={{ fill: series(p.i) }}
            stroke="var(--card)"
            strokeWidth={1.5}
          >
            <title>{label}</title>
          </path>
        );
      })}
    </g>
  );
}
