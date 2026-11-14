/*
 * React helpers for OmniHarness apps (the app kit). Written by the system; do
 * not edit — copy the pattern if you need something different.
 *
 *   <Tile source="calendar" title="Calendar" empty="No meetings today" View={CalendarView} />
 *
 * Tile renders the four honest states with the standard words (a skeleton
 * while waiting, "updated N min ago", "Nothing today", "Not connected" with a
 * Connect button, "Can't tell" with the reason, "May be out of date"). You
 * write only each tile's fresh view, as a COMPONENT (so its own hooks are
 * always called in the same order).
 */
import { createElement, useEffect, useState, type ComponentType, type ReactNode } from "react";

import type { DataOf, SourceName, SourceResult } from "./omni";

export function useSource<K extends SourceName>(name: K): { result: SourceResult<DataOf<K>> | null; refresh: () => void } {
  // Every hook first, unconditionally (never after an early return).
  const [result, setResult] = useState<SourceResult<DataOf<K>> | null>(null);
  const [, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    omni.data(name).then(
      (r) => live && setResult(r),
      (e: unknown) => live && setResult({ source: name, state: "failed", data: null, fetched_at: null, stale: false, reason: e instanceof Error ? e.message : String(e) }),
    );
    const off = omni.onUpdate((n, r) => {
      if (live && n === name) setResult(r as SourceResult<DataOf<K>>);
    });
    // Keep "updated N min ago" current.
    const timer = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => {
      live = false;
      off();
      clearInterval(timer);
    };
  }, [name]);
  const refresh = () => {
    omni.refresh(name).then(setResult, () => undefined);
  };
  return { result, refresh };
}

export interface TileProps<K extends SourceName> {
  source: K;
  title: string;
  /** The tile's own wording of nothing ("No PRs waiting on you"). */
  empty?: string;
  className?: string;
  /** The fresh view: a component receiving the source's data. */
  View: ComponentType<{ data: DataOf<K>; result: SourceResult<DataOf<K>> }>;
}

export function Tile<K extends SourceName>({ source, title, empty = "Nothing today", className, View }: TileProps<K>) {
  const { result } = useSource(source);
  const words = omni.describe(result);
  let body: ReactNode;
  if (result === null) {
    body = (
      <>
        <span className="omni-skeleton" />
        <span className="omni-skeleton" style={{ width: "60%" }} />
      </>
    );
  } else if (result.state === "fresh" && result.data !== null) {
    body = (
      <>
        {createElement(View, { data: result.data, result })}
        {result.stale ? <p className="omni-stale">May be out of date</p> : null}
      </>
    );
  } else if (result.state === "failed" && result.data !== null) {
    body = (
      <>
        <div className="omni-state omni-state-failed">
          <span className="omni-state-label">Can&apos;t tell</span>
          <span className="omni-state-detail">{words.detail}</span>
        </div>
        {createElement(View, { data: result.data, result })}
        <p className="omni-stale">May be out of date</p>
      </>
    );
  } else {
    body = (
      <div className={"omni-state" + (result.state === "failed" ? " omni-state-failed" : "")}>
        <span className="omni-state-label">{result.state === "empty" ? empty : words.label}</span>
        {result.state === "empty" ? null : <span className="omni-state-detail">{words.detail}</span>}
        {result.state === "not_connected" ? (
          <button type="button" className="omni-button omni-button-primary" onClick={() => omni.connect(source)}>
            Connect
          </button>
        ) : null}
      </div>
    );
  }
  const fresh = result !== null && (result.state === "fresh" || result.state === "empty");
  return (
    <section className={"omni-tile" + (className ? " " + className : "")} aria-busy={result === null}>
      <div className="omni-tile-head">
        <h2 className="omni-tile-title">{title}</h2>
        {fresh ? <span className="omni-tile-meta">{"updated " + omni.ago(result.fetched_at)}</span> : null}
      </div>
      {body}
    </section>
  );
}

// -- time, in the app's own time zone -------------------------------------------------

/**
 * Every time is formatted and positioned with this, in the app's time zone
 * (TIME_ZONE from omni-kit/app-config), never with getHours() or the
 * browser's zone. One implementation, Intl-based.
 */
export function zoned(tz: string) {
  const time = new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "numeric", minute: "2-digit" });
  const day = new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short", month: "short", day: "numeric" });
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const toDate = (d: Date | string) => (typeof d === "string" ? new Date(d) : d);
  const fields = (d: Date | string) => {
    const out: Record<string, string> = {};
    for (const p of parts.formatToParts(toDate(d))) out[p.type] = p.value;
    return out;
  };
  return {
    /** "9:30 AM" */
    formatTime: (d: Date | string) => time.format(toDate(d)),
    /** "Wed, Jan 14" */
    formatDay: (d: Date | string) => day.format(toDate(d)),
    /** Minutes since local midnight (0 to 1439). */
    minutesIntoDay: (d: Date | string) => {
      const f = fields(d);
      return Number(f.hour) * 60 + Number(f.minute);
    },
    /** The local calendar date, "2026-01-14". An all-day event's date is already one. */
    dateOf: (d: Date | string) => {
      if (typeof d === "string" && /^\d{4}-\d{2}-\d{2}$/.test(d)) return d;
      const f = fields(d);
      return `${f.year}-${f.month}-${f.day}`;
    },
    /** Same local day as `now` (pass omni.now()). */
    isToday: (d: Date | string, now: Date) => {
      const f = (x: Date | string) => (typeof x === "string" && /^\d{4}-\d{2}-\d{2}$/.test(x) ? x : `${fields(x).year}-${fields(x).month}-${fields(x).day}`);
      return f(d) === f(now);
    },
  };
}

// -- building blocks ---------------------------------------------------------------------

/** A list row: the title truncates (with the full text as a tooltip), the meta stays. */
export function Row({ title, meta, badge, href }: { title: string; meta?: string; badge?: ReactNode; href?: string | null }) {
  const label = href ? (
    <a className="omni-row-title" href={href} title={title}>
      {title}
    </a>
  ) : (
    <span className="omni-row-title" title={title}>
      {title}
    </span>
  );
  return (
    <li className="omni-row">
      {badge ? <span className="omni-row-badge">{badge}</span> : null}
      {label}
      {meta ? <span className="omni-row-meta">{meta}</span> : null}
    </li>
  );
}

/** One number and what it counts. */
export function Stat({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="omni-kpi">
      <span className="omni-kpi-value">{value}</span>
      <span className="omni-kpi-label">{label}</span>
    </div>
  );
}

export interface TimelineEvent {
  title?: string;
  start?: string;
  end?: string | null;
  all_day?: boolean;
}

/**
 * A day strip in SVG: each timed event a block positioned in the app's time
 * zone, its title inside only when it fits, free time hatched, a line at now,
 * hour labels (12 px). Scrolls inside its card on a phone.
 */
export function Timeline({ events, tz, from = 8, to = 19, now }: { events: TimelineEvent[]; tz: string; from?: number; to?: number; now: Date }) {
  const z = zoned(tz);
  const W = 720;
  const H = 64;
  const top = 8;
  const bar = 30;
  const span = (to - from) * 60;
  const x = (min: number) => Math.max(0, Math.min(W, ((min - from * 60) / span) * W));
  const timed = events.filter((e) => !e.all_day && e.start && e.end && z.isToday(e.start, now));
  const nowX = x(z.minutesIntoDay(now));
  const hours = Array.from({ length: to - from + 1 }, (_, i) => from + i);
  return (
    <div className="omni-timeline" role="img" aria-label={`Today's meetings: ${timed.map((e) => `${e.title ?? ""} at ${z.formatTime(e.start!)}`).join(", ") || "none"}`}>
      <svg className="omni-chart" viewBox={`0 0 ${W} ${H + 20}`} preserveAspectRatio="xMinYMin meet">
        <defs>
          <pattern id="omni-free" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" className="omni-free-line" />
          </pattern>
        </defs>
        <rect x={0} y={top} width={W} height={bar} fill="url(#omni-free)" className="omni-free" />
        {timed.map((e, i) => {
          const a = x(z.minutesIntoDay(e.start!));
          const b = x(z.minutesIntoDay(e.end!));
          const w = Math.max(3, b - a);
          const label = e.title ?? "";
          // About 7 px per character at 12 px: only a label that fits is drawn inside.
          const fits = label.length * 7 + 12 <= w;
          return (
            <g key={i}>
              <rect x={a} y={top} width={w} height={bar} rx={4} className="omni-series" />
              {fits ? (
                <text x={a + 6} y={top + bar / 2 + 4} className="omni-timeline-label">
                  {label}
                </text>
              ) : null}
            </g>
          );
        })}
        <line x1={nowX} x2={nowX} y1={top - 4} y2={top + bar + 4} className="omni-now" />
        {hours.map((h) => (
          <text key={h} x={Math.min(Math.max(x(h * 60), 10), W - 10)} y={H + 14} textAnchor="middle" className="omni-timeline-hour">
            {h % 12 || 12}
            {h < 12 ? "a" : "p"}
          </text>
        ))}
      </svg>
    </div>
  );
}

/** A tiny bar chart of daily counts, with a text alternative. */
export function Sparkline({ days, label }: { days: { day: string; value: number }[]; label: string }) {
  const max = Math.max(1, ...days.map((d) => d.value));
  const W = Math.max(1, days.length) * 14;
  return (
    <svg className="omni-chart omni-sparkline" viewBox={`0 0 ${W} 28`} role="img" aria-label={`${label}: ${days.map((d) => `${d.day} ${d.value}`).join(", ")}`}>
      {days.map((d, i) => {
        const h = Math.round((d.value / max) * 24);
        return <rect key={d.day} x={i * 14 + 2} y={26 - h} width={10} height={Math.max(1, h)} rx={2} className="omni-series" />;
      })}
    </svg>
  );
}
