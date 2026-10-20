"use client";

import { useEffect, useSyncExternalStore } from "react";
import type { PluginConfig } from "streamdown";

/**
 * Code highlighting (shiki) and math (katex) load only when a message needs
 * them (Phase 2.6). streamdown 2 keeps both out of its core; their plugins are
 * imported here the first time a message contains a code fence or math, then
 * every renderer re-renders with them.
 *
 * Until a plugin arrives, a code fence renders as plain preformatted text and
 * math as its source, for the moment the import takes.
 */
const FENCE = /(^|\n)[ \t]*(```|~~~)/;
// $$..$$, \(..\), \[..\], or $x$ with no space just inside the dollars.
const MATH = /\$\$|\\\(|\\\[|(^|[^\\$\w])\$[^\s$][^$\n]*[^\s$\\]\$/;

let loaded: PluginConfig = {};
const loading: Partial<Record<"code" | "math", Promise<void>>> = {};
const listeners = new Set<() => void>();

function load(kind: "code" | "math") {
  if (loaded[kind] || loading[kind]) return;
  const plugin =
    kind === "code"
      ? import("@streamdown/code").then((m) => m.code)
      : Promise.all([
          import("@streamdown/math"),
          // katex's stylesheet, loaded with the plugin rather than globally.
          import("katex/dist/katex.min.css"),
        ]).then(([m]) => m.createMathPlugin({ singleDollarTextMath: true }));
  loading[kind] = plugin
    .then((p) => {
      loaded = { ...loaded, [kind]: p };
      listeners.forEach((l) => l());
    })
    .catch(() => {
      // Leave it unloaded; text still renders, unhighlighted.
      delete loading[kind];
    });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function needsCode(text: string) {
  return FENCE.test(text);
}

export function needsMath(text: string) {
  return MATH.test(text);
}

/** The plugins this text needs, loading them on first use. */
export function useMarkdownPlugins(text: string | undefined): PluginConfig {
  const plugins = useSyncExternalStore(
    subscribe,
    () => loaded,
    () => loaded,
  );
  const code = text ? needsCode(text) : false;
  const math = text ? needsMath(text) : false;
  useEffect(() => {
    if (code) load("code");
    if (math) load("math");
  }, [code, math]);
  return plugins;
}
