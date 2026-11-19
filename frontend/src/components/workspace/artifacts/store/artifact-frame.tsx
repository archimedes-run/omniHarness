"use client";

import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  ExternalLinkIcon,
  Loader2Icon,
  MaximizeIcon,
  PlayIcon,
  RefreshCwIcon,
} from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  ArtifactFrameController,
  frameSrc,
  readThemeVars,
  type FrameTheme,
} from "@/core/artifacts/frame-host";
import { LinkGate, splitLink } from "@/core/artifacts/link-gate";
import {
  liveSlotHolder,
  setCardVisible,
  subscribeLiveSlot,
} from "@/core/artifacts/live-slot";
import {
  getFrameToken,
  reportFrameRefusal,
  shotUrl,
  type ArtifactDetail,
  type ArtifactSummary,
  type CheckInfo,
} from "@/core/artifacts/store-api";
import { useCodeActions } from "@/core/artifacts/store-hooks";
import {
  checkWords,
  refusalWords,
  titleText,
} from "@/core/artifacts/store-logic";
import { safeField } from "@/core/display/safe";
import { cn } from "@/lib/utils";

import { KindIcon } from "./artifact-content";

/**
 * Spec 012 FR-016, FR-019: the LOCKED FRAME for html and react artifacts.
 * The iframe's sandbox is exactly "allow-scripts" (an opaque origin: no
 * cookies, no storage, no access to this page); its document comes from the
 * gateway's frame route under the artifact profile, only with a short-lived
 * view token. The host gives it a theme and nothing else (frame-host.ts).
 * No artifact markup ever reaches this page's DOM.
 */
export interface LockedFrameProps {
  /** The artifact (an html, react or webapp kind). */
  artifactId: string;
  /** The version to show (immutable). */
  version: number;
  /** webapp only: the page to show, a relative path inside its file set
   * (default: its entry). The gateway validates it. */
  entry?: string;
  /** Names the frame for assistive technology (shown as text only). */
  title: string;
  /** "inline": a chat card (height follows the frame, capped); "panel":
   * fills its box (the side panel, the full page, full screen). */
  variant: "inline" | "panel";
  className?: string;
  /** The viewer's preview theme; absent, the app's theme (as before). */
  theme?: FrameTheme;
}

/** The locked frame, standalone: usable anywhere in the app (the chat
 * card, the panel, the store's full page). */
export function LockedFrame({
  artifactId,
  version,
  entry,
  title,
  variant,
  className,
  theme: themeProp,
}: LockedFrameProps) {
  const { resolvedTheme } = useTheme();
  const theme: FrameTheme =
    themeProp ?? (resolvedTheme === "dark" ? "dark" : "light");
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const controllerRef = useRef<ArtifactFrameController | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [height, setHeight] = useState(variant === "inline" ? 220 : 600);
  const [torn, setTorn] = useState(false);
  const [link, setLinkState] = useState<string | null>(null);
  const linkGate = useRef(new LinkGate());
  const setLink = (value: string | null) => {
    if (value === null) linkGate.current.closed(Date.now());
    setLinkState(value);
  };
  const [attempt, setAttempt] = useState(0);
  const themeRef = useRef(theme);
  themeRef.current = theme;
  const themePropRef = useRef(themeProp);
  themePropRef.current = themeProp;

  useEffect(() => {
    let live = true;
    setSrc(null);
    setError(null);
    setTorn(false);
    const controller = new ArtifactFrameController({
      theme: themeRef.current,
      vars: readThemeVars(themePropRef.current),
      onSize: (h) => live && setHeight(h),
      onOpenRequest: (url) => {
        if (!live) return;
        const r = linkGate.current.request(
          url,
          document.activeElement === frameRef.current,
          Date.now(),
        );
        if (r.ok) setLink(url);
        else reportFrameRefusal(artifactId, { reason: r.reason, type: "open" });
      },
      onTornDown: () => live && setTorn(true),
      reportRefusal: (r) => reportFrameRefusal(artifactId, r),
    });
    controllerRef.current = controller;
    const onMessage = (e: MessageEvent) => controller.handleWindowMessage(e);
    window.addEventListener("message", onMessage);
    getFrameToken(artifactId, version)
      .then((t) => {
        if (!live) return;
        const url = entry
          ? `${t.url}&path=${encodeURIComponent(entry)}`
          : t.url;
        setSrc(frameSrc(url, controller.nonce, themeRef.current));
      })
      .catch((err) => live && setError(refusalWords(err)));
    return () => {
      live = false;
      window.removeEventListener("message", onMessage);
      controller.dispose();
      controllerRef.current = null;
    };
  }, [artifactId, version, entry, attempt]);

  useEffect(() => {
    const id = requestAnimationFrame(() =>
      controllerRef.current?.setTheme(theme, readThemeVars(themeProp)),
    );
    return () => cancelAnimationFrame(id);
  }, [theme, themeProp]);

  const parts = link ? splitLink(link) : null;
  const host = link ? new URL(link).host : "";
  return (
    <div
      className={cn("relative min-w-0", className)}
      data-testid="artifact-frame-box"
    >
      {error ? (
        <p className="text-muted-foreground p-3 text-sm" role="status">
          {error}
        </p>
      ) : torn ? (
        <div
          className="flex flex-col items-start gap-2 p-3 text-sm"
          role="status"
          data-testid="artifact-frame-stopped"
        >
          <span className="text-muted-foreground">
            This preview stopped: it reloaded or replaced itself.
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setAttempt((a) => a + 1)}
            className="max-md:min-h-11"
          >
            <RefreshCwIcon />
            Start again
          </Button>
        </div>
      ) : src ? (
        <iframe
          ref={(el) => {
            frameRef.current = el;
            if (el) controllerRef.current?.attach(el);
          }}
          key={src}
          src={src}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          title={`${title} (sandboxed preview)`}
          data-testid="artifact-frame"
          onLoad={() => controllerRef.current?.handleLoad()}
          className="bg-background block w-full rounded-md border-0"
          style={
            variant === "inline"
              ? { height: Math.min(height, 360) }
              : { height: "100%", minHeight: Math.max(height, 480) }
          }
        />
      ) : (
        <p
          className="text-muted-foreground flex items-center gap-2 p-3 text-sm"
          role="status"
        >
          <Loader2Icon className="size-4 animate-spin" aria-hidden />
          Starting the preview…
        </p>
      )}
      <Dialog open={!!link} onOpenChange={(o) => !o && setLink(null)}>
        <DialogContent data-testid="artifact-open-link">
          <DialogHeader>
            <DialogTitle>Open link?</DialogTitle>
            <DialogDescription>
              The artifact wants to open a page on{" "}
              <strong className="text-foreground break-all">
                {safeField(host)}
              </strong>
              . It opens in a new tab, without this app&rsquo;s session.
            </DialogDescription>
            {parts && (
              <p
                className="bg-muted rounded-md px-2 py-1 font-mono text-xs break-all"
                data-testid="artifact-open-link-url"
              >
                <span>{safeField(parts.base)}</span>
                {parts.rest && (
                  <mark
                    className="bg-warning/25 text-foreground rounded-sm"
                    title="Everything after the address is sent to that site"
                  >
                    {safeField(parts.rest)}
                  </mark>
                )}
              </p>
            )}
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setLink(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => {
                if (link) window.open(link, "_blank", "noopener,noreferrer");
                setLink(null);
              }}
              data-testid="artifact-open-link-confirm"
            >
              <ExternalLinkIcon />
              Open {safeField(host)}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** The checks' label for a code version (FR-018): always text. */
export function CheckLabel({
  check,
  onCheckAgain,
  pending,
}: {
  check: CheckInfo | null | undefined;
  onCheckAgain?: () => void;
  pending?: boolean;
}) {
  const words = checkWords(check?.state, check?.summary);
  const Icon =
    words.tone === "ok"
      ? CheckCircle2Icon
      : words.tone === "warn"
        ? AlertTriangleIcon
        : Loader2Icon;
  return (
    <div
      className="flex min-w-0 flex-wrap items-center gap-2"
      data-testid="artifact-check"
      data-state={check?.state ?? "none"}
    >
      <p
        className={cn(
          "flex min-w-0 items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs",
          words.tone === "ok" && "border-success/40",
          words.tone === "warn" && "border-warning/50",
          words.tone === "muted" && "border-border text-muted-foreground",
        )}
      >
        <Icon
          className={cn(
            "size-3.5 shrink-0",
            words.tone === "muted" && "animate-spin",
          )}
          aria-hidden
        />
        <span className="min-w-0 break-words">{words.label}</span>
      </p>
      {check?.state === "not_checked" && onCheckAgain && (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={onCheckAgain}
          disabled={pending}
          className="h-7 max-md:min-h-11"
          data-testid="artifact-check-again"
        >
          <RefreshCwIcon />
          Check again
        </Button>
      )}
    </div>
  );
}

/** The failures and findings of a version: the page's own words, as text. */
export function CheckDetails({
  check,
  findings,
}: {
  check: CheckInfo | null | undefined;
  findings: string[];
}) {
  const failures = check?.failures ?? [];
  if (!failures.length && !findings.length) return null;
  return (
    <details
      className="text-muted-foreground text-xs"
      data-testid="artifact-check-details"
    >
      <summary className="cursor-pointer select-none">Details</summary>
      <ul className="mt-1 list-disc pl-5">
        {failures.map((f, i) => (
          <li key={`f${i}`}>{safeField(f)}</li>
        ))}
        {findings.map((f, i) => (
          <li key={`s${i}`}>{safeField(f)}</li>
        ))}
      </ul>
    </details>
  );
}

/** A static preview: the checks' screenshot, else the kind's icon. Never a frame. */
export function ShotPreview({
  artifact,
  version,
  check,
  className,
}: {
  artifact: Pick<ArtifactDetail, "id" | "kind" | "title">;
  version: number;
  check: CheckInfo | null | undefined;
  className?: string;
}) {
  const { resolvedTheme } = useTheme();
  const theme = resolvedTheme === "dark" ? "dark" : "light";
  const has = check?.shots?.[theme] ?? false;
  const [broken, setBroken] = useState(false);
  if (has && !broken) {
    return (
      <img
        src={shotUrl(artifact.id, version, theme)}
        alt={`${titleText(artifact.title)} (screenshot)`}
        className={cn(
          "border-border block w-full rounded-md border object-cover object-top",
          className,
        )}
        onError={() => setBroken(true)}
        data-testid="artifact-shot"
      />
    );
  }
  return (
    <div
      className={cn(
        "bg-muted text-muted-foreground flex items-center justify-center rounded-md",
        className,
      )}
      data-testid="artifact-shot-icon"
    >
      <KindIcon kind={artifact.kind} className="size-8" />
    </div>
  );
}

/**
 * The inline card's preview of a code version: live in the locked frame when
 * the checks passed, the card is on screen and it holds the one live slot;
 * otherwise the screenshot. A version that failed or was not checked shows
 * its label and an "Open anyway" button instead (FR-018).
 */
export function CodeCardPreview({
  artifact,
  version,
  onOpen,
}: {
  artifact: ArtifactDetail;
  version: number;
  onOpen: () => void;
}) {
  const v = artifact.versions.find((x) => x.n === version);
  const code = v?.code;
  const key = `${artifact.id}:${version}:${useId()}`;
  const box = useRef<HTMLDivElement | null>(null);
  const [holder, setHolder] = useState<string | null>(liveSlotHolder());
  const actions = useCodeActions(artifact.id);
  const passed = code?.build_state === "ok" && code.check?.state === "passed";

  useEffect(() => subscribeLiveSlot(setHolder), []);
  useEffect(() => {
    const el = box.current;
    if (!el || !passed || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries)
          setCardVisible(key, e.isIntersecting && e.intersectionRatio > 0.5);
      },
      { threshold: [0, 0.5, 1] },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      setCardVisible(key, false);
    };
  }, [key, passed]);

  if (!code) return null;
  if (code.build_state === "build_failed") {
    const shown = artifact.code?.shown_version;
    return (
      <div className="flex flex-col gap-1" data-testid="artifact-build-failed">
        <p className="border-warning/50 flex w-fit items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs">
          <AlertTriangleIcon className="size-3.5" aria-hidden />
          The build failed
          {shown ? `; version ${shown} stays the one shown` : ""}.
        </p>
      </div>
    );
  }
  return (
    <div
      ref={box}
      className="flex min-w-0 flex-col gap-2"
      data-testid="artifact-code-preview"
    >
      <CheckLabel
        check={code.check}
        pending={actions.checkAgain.isPending}
        onCheckAgain={() => actions.checkAgain.mutate(version)}
      />
      {passed ? (
        holder === key ? (
          <LockedFrame
            artifactId={artifact.id}
            version={version}
            title={titleText(artifact.title)}
            variant="inline"
          />
        ) : (
          <ShotPreview
            artifact={artifact}
            version={version}
            check={code.check}
            className="h-40"
          />
        )
      ) : code.check?.state === "pending" ? null : (
        <div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onOpen}
            data-testid="artifact-open-anyway"
            className="max-md:min-h-11"
          >
            <PlayIcon />
            Open anyway
          </Button>
        </div>
      )}
    </div>
  );
}

/** Full screen for the opened view (the panel or the page). */
export function FullscreenButton({
  target,
}: {
  target: React.RefObject<HTMLElement | null>;
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      onClick={() =>
        void target.current?.requestFullscreen?.().catch(() => undefined)
      }
      data-testid="artifact-fullscreen"
      className="max-md:min-h-11"
    >
      <MaximizeIcon />
      Full screen
    </Button>
  );
}

/** The store grid's preview of a code artifact: a screenshot or an icon. */
export function StoreShot({
  artifact,
}: {
  artifact: Pick<ArtifactSummary, "id" | "kind" | "title" | "code">;
}) {
  const { resolvedTheme } = useTheme();
  const theme = resolvedTheme === "dark" ? "dark" : "light";
  const [broken, setBroken] = useState(false);
  const n = artifact.code?.shown_version;
  const state = artifact.code?.check_state;
  const tryShot =
    !!n &&
    !broken &&
    (state === "passed" ||
      state === "failed" ||
      artifact.code?.build_state === "build_failed");
  return tryShot ? (
    <img
      src={shotUrl(artifact.id, n, theme)}
      alt={`${titleText(artifact.title)} (screenshot)`}
      className="block h-full w-full rounded-md object-cover object-top"
      onError={() => setBroken(true)}
      data-testid="artifact-shot"
    />
  ) : (
    <div
      className="text-muted-foreground flex h-full items-center justify-center"
      data-testid="artifact-shot-icon"
    >
      <KindIcon kind={artifact.kind} className="size-8" />
    </div>
  );
}
