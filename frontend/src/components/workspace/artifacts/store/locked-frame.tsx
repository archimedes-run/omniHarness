"use client";

import { useTheme } from "next-themes";
import { useEffect, useRef, useState } from "react";

import { ArtifactsApiError, frameToken } from "@/core/artifacts/store-api";

/**
 * Spec 012 FR-016/FR-019: a code artifact (html, react, an imported web
 * app) in the LOCKED FRAME, per api.md "The frame protocol". The gateway
 * serves the document under the artifact profile; this side embeds it with
 * `sandbox="allow-scripts"` exactly, a per-view nonce in the fragment, and
 * answers exactly one hello (from the frame's own window, with that nonce)
 * after exactly one load with `init` and a MessageChannel port. On the port
 * it accepts only `ready` and `size`; a link the frame asks to open
 * (`open`) is not opened here. A second load or hello, or a wrong nonce,
 * tears the frame down.
 *
 * The full locked-frame component of Slice 2 (its "Open link?" dialog and
 * refusal reporting) replaces this one when it lands; the props stay
 * `{artifactId, version, title}`.
 */

const MIN = 120;
const MAX = 1200;

function nonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

type State =
  | { s: "loading" }
  | { s: "running"; src: string }
  | { s: "stopped"; why: string };

export function LockedFrame({
  artifactId,
  version,
  title,
}: {
  artifactId: string;
  version: number;
  title: string;
}) {
  const { resolvedTheme } = useTheme();
  const theme = resolvedTheme === "dark" ? "dark" : "light";
  const ref = useRef<HTMLIFrameElement>(null);
  const portRef = useRef<MessagePort | null>(null);
  const [state, setState] = useState<State>({ s: "loading" });
  const [height, setHeight] = useState(480);
  const themeRef = useRef(theme);
  themeRef.current = theme;

  useEffect(() => {
    let live = true;
    const n = nonce();
    let loads = 0;
    let hellos = 0;
    let answered = false;
    const stop = (why: string) => {
      if (!live) return;
      portRef.current?.close();
      portRef.current = null;
      setState({ s: "stopped", why });
    };
    const maybeInit = () => {
      const win = ref.current?.contentWindow;
      if (answered || loads !== 1 || hellos !== 1 || !win) return;
      answered = true;
      const channel = new MessageChannel();
      channel.port1.onmessage = (e: MessageEvent) => {
        const d = e.data as { v?: unknown; type?: unknown; height?: unknown };
        if (d?.v !== 1) return;
        if (d.type === "size" && typeof d.height === "number") {
          setHeight(Math.max(MIN, Math.min(MAX, Math.round(d.height))));
        }
        // "ready" needs nothing; "open" and anything else are dropped.
      };
      portRef.current = channel.port1;
      win.postMessage(
        { v: 1, type: "init", theme: themeRef.current, vars: {} },
        "*",
        [channel.port2],
      );
    };
    const onMessage = (e: MessageEvent) => {
      const win = ref.current?.contentWindow;
      if (!win || e.source !== win) return;
      const d = e.data as { v?: unknown; type?: unknown; nonce?: unknown };
      if (d?.v !== 1 || d.type !== "hello") return;
      hellos += 1;
      if (hellos > 1 || d.nonce !== n) {
        stop("The page did something it may not, so it was stopped.");
        return;
      }
      maybeInit();
    };
    window.addEventListener("message", onMessage);
    const frame = ref.current;
    const onLoad = () => {
      if (!frame?.getAttribute("src")) return;
      loads += 1;
      if (loads > 1) {
        stop("The page tried to reload itself, so it was stopped.");
        return;
      }
      maybeInit();
    };
    frame?.addEventListener("load", onLoad);
    setState({ s: "loading" });
    frameToken(artifactId, version)
      .then((t) => {
        if (!live) return;
        if (!t.url.startsWith(`/api/artifacts/`)) {
          stop("This page can't be shown.");
          return;
        }
        setState({
          s: "running",
          src: `${t.url}#n=${n}&t=${themeRef.current}`,
        });
      })
      .catch((err: unknown) => {
        stop(
          err instanceof ArtifactsApiError && err.code === "build_failed"
            ? "This version did not build, so there is nothing to show."
            : "This page can't be shown right now.",
        );
      });
    return () => {
      live = false;
      window.removeEventListener("message", onMessage);
      frame?.removeEventListener("load", onLoad);
      portRef.current?.close();
      portRef.current = null;
    };
  }, [artifactId, version]);

  useEffect(() => {
    portRef.current?.postMessage({ v: 1, type: "theme", theme, vars: {} });
  }, [theme]);

  if (state.s === "stopped") {
    return (
      <p
        className="text-muted-foreground text-sm"
        role="status"
        data-testid="artifact-frame-stopped"
      >
        {state.why}
      </p>
    );
  }
  return (
    <iframe
      ref={ref}
      title={title}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      src={state.s === "running" ? state.src : undefined}
      data-testid="artifact-frame"
      className="border-border bg-background block w-full rounded-md border"
      style={{ height }}
    />
  );
}
