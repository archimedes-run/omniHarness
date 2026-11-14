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
