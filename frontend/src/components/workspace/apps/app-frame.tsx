"use client";

import { RotateCcwIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  getAppData,
  getAppSource,
  reportRefusedMessage,
  type AppDetail,
  type BatchData,
} from "@/core/apps/api";
import { AppHostController } from "@/core/apps/host-controller";
import type { SourceResult, Theme } from "@/core/apps/protocol";

/** FR-017: exactly this, nothing more. */
export const APP_FRAME_SANDBOX = "allow-scripts";

/** The served document, always on this origin (the host's frame-src 'self'). */
export function appHtmlPath(id: string, version: number): string {
  return `/api/apps/${encodeURIComponent(id)}/versions/${version}/app.html`;
}

/** How often the host re-reads the shared cache and pushes `update`s. */
const POLL_MS = 60_000;

function currentTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function stamp(r: SourceResult | null | undefined): string {
  return r ? `${r.state}|${r.fetched_at ?? ""}|${r.stale}` : "";
}

/**
 * The app's sandboxed frame and its host controller (Spec 011 FR-017,
 * FR-020..FR-024, FR-031). The iframe is made here, by hand, so its load
 * listener exists before its first load and React never re-creates or moves
 * it (a moved iframe reloads, and a second load tears it down).
 *
 * The batch `GET /data` starts in the same tick as the frame, so the frame's
 * first `data` requests are answered from it.
 */
export function AppFrame({
  app,
  onConnect,
  connected,
  takePrefetch,
}: {
  app: AppDetail;
  /** The batch read the page started with the app's own read (FR-031),
   * handed over once; later opens (Reopen) start their own. */
  takePrefetch?: () => Promise<BatchData> | null;
  onConnect: (source: string) => void;
  /** A source just connected through the sheet: refetch and push it. */
  connected: { source: string; at: number } | null;
}) {
  const router = useRouter();
  const box = useRef<HTMLDivElement>(null);
  const controllerRef = useRef<AppHostController | null>(null);
  const lastSent = useRef(new Map<string, string>());
  const [nonce, setNonce] = useState(0);
  const [torn, setTorn] = useState(false);
  const onConnectRef = useRef(onConnect);
  useEffect(() => {
    onConnectRef.current = onConnect;
  }, [onConnect]);
  const takeRef = useRef(takePrefetch);

  const id = app.id;
  const version = app.current_version;
  const sources = app.sources.map((s) => s.name).join(",");
  const linkHosts = [...new Set(app.sources.flatMap((s) => s.link_hosts))]
    .sort()
    .join(",");

  useEffect(() => {
    const container = box.current;
    if (!container) return;
    setTorn(false);
    lastSent.current = new Map();
    const prefetch = (takeRef.current?.() ?? getAppData(id))
      .then((batch) => {
        if (batch.version !== version) return null;
        for (const [name, r] of Object.entries(batch.results)) {
          lastSent.current.set(name, stamp(r));
        }
        return batch.results;
      })
      .catch(() => null);

    const frame = document.createElement("iframe");
    const controller = new AppHostController({
      appId: id,
      version,
      approvedSources: sources ? sources.split(",") : [],
      linkHosts: linkHosts ? linkHosts.split(",") : [],
      origin: window.location.origin,
      theme: currentTheme(),
      prefetch,
      fetchSource: async (source, refresh) => {
        const r = await getAppSource(id, source, refresh);
        lastSent.current.set(source, stamp(r));
        return r;
      },
      reportRefusal: (refusal) => {
        void reportRefusedMessage(id, refusal).catch(() => undefined);
      },
      openExternal: (url) => {
        window.open(url, "_blank", "noopener,noreferrer");
      },
      openInternal: (path) => router.push(path),
      onConnect: (source) => onConnectRef.current(source),
      onTornDown: () => {
        frame.remove();
        setTorn(true);
      },
    });
    controllerRef.current = controller;
    controller.attach(frame);

    const onLoad = () => controller.handleLoad();
    const onMessage = (event: MessageEvent) =>
      controller.handleWindowMessage(event);
    frame.addEventListener("load", onLoad);
    window.addEventListener("message", onMessage);

    frame.setAttribute("sandbox", APP_FRAME_SANDBOX);
    frame.setAttribute("referrerpolicy", "no-referrer");
    frame.setAttribute(
      "allow",
      "camera 'none'; microphone 'none'; geolocation 'none'; payment 'none'; usb 'none'; clipboard-read 'none'; clipboard-write 'none'",
    );
    frame.setAttribute("title", app.name);
    frame.setAttribute("data-testid", "app-frame");
    frame.className = "bg-background block size-full border-0";
    frame.src = appHtmlPath(id, version);
    container.appendChild(frame);

    // The theme follows the page's, live.
    const observer = new MutationObserver(() =>
      controller.setTheme(currentTheme()),
    );
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });

    // Re-read the shared cache; push what changed.
    const poll = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void getAppData(id)
        .then((batch) => {
          if (batch.version !== version) return;
          for (const [name, r] of Object.entries(batch.results)) {
            if (lastSent.current.get(name) === stamp(r)) continue;
            lastSent.current.set(name, stamp(r));
            controller.pushUpdate(name, r);
          }
        })
        .catch(() => undefined);
    }, POLL_MS);

    return () => {
      window.clearInterval(poll);
      observer.disconnect();
      window.removeEventListener("message", onMessage);
      frame.removeEventListener("load", onLoad);
      controller.dispose();
      frame.remove();
      controllerRef.current = null;
    };
    // `app.name` only titles the frame; a rename must not reload the app.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, version, sources, linkHosts, nonce, router]);

  useEffect(() => {
    if (!connected) return;
    const controller = controllerRef.current;
    if (!controller) return;
    void getAppSource(id, connected.source, true)
      .then((r) => {
        lastSent.current.set(connected.source, stamp(r));
        controller.pushUpdate(connected.source, r);
      })
      .catch(() => undefined);
  }, [connected, id]);

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={box} className="absolute inset-0" data-testid="app-frame-box" />
      {torn && (
        <div
          className="bg-background absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center"
          role="alert"
          data-testid="app-reloaded"
        >
          <p className="text-[15px] font-medium">
            This app reloaded itself. Reopen it.
          </p>
          <p className="text-muted-foreground max-w-[420px] text-sm">
            An app may load only once. It was closed so that nothing it loaded
            the second time can talk to this page.
          </p>
          <Button
            type="button"
            variant="outline"
            onClick={() => setNonce((n) => n + 1)}
            data-testid="app-reopen"
            className="max-md:min-h-11"
          >
            <RotateCcwIcon />
            Reopen
          </Button>
        </div>
      )}
    </div>
  );
}
