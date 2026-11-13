"use client";

import {
  ArrowLeftIcon,
  Maximize2Icon,
  Minimize2Icon,
  ShieldAlertIcon,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { AppApprovalCard } from "@/components/workspace/confirmations/app-approval-card";
import { StatusWord } from "@/components/workspace/page-kit";
import {
  AppsApiError,
  getAppData,
  type AppDetail,
  type BatchData,
} from "@/core/apps/api";
import { useApp, useAppCatalog, usePendingApproval } from "@/core/apps/hooks";
import { STATUS_TONE, STATUS_WORDS } from "@/core/apps/wording";
import { cn } from "@/lib/utils";

import { AppFrame } from "./app-frame";
import { ConnectSheet } from "./connect-sheet";

/**
 * Spec 011 FR-029, FR-031: the trusted host page of one app,
 * /workspace/apps/{id}. The app's frame fills the page; Full screen covers the
 * workspace too (the same frame, restyled: moving an iframe would reload it).
 *
 * An app whose current version is not approved shows no frame: its App access
 * card instead (Needs approval), or the Approve again card after Revoke.
 */
export function AppHostPage({ appId }: { appId: string }) {
  // The batch read starts with the app's own read, not after it (FR-031).
  const early = useRef<Promise<BatchData> | null>(null);
  useEffect(() => {
    const p = getAppData(appId);
    p.catch(() => undefined);
    early.current = p;
  }, [appId]);
  const takePrefetch = useCallback(() => {
    const p = early.current;
    early.current = null;
    return p;
  }, []);

  const { data: app, error, isLoading } = useApp(appId);
  const [full, setFull] = useState(false);

  useEffect(() => {
    if (!full) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFull(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [full]);

  if (isLoading) {
    return (
      <div
        className="text-muted-foreground p-8 text-sm"
        data-testid="app-host-loading"
      >
        Opening the app…
      </div>
    );
  }
  if (error || !app) {
    return (
      <div className="flex flex-col items-start gap-3 p-8 text-sm" role="alert">
        <p className="font-medium">
          {error instanceof AppsApiError && error.status === 404
            ? "There is no app with this link."
            : "Could not open this app."}
        </p>
        {error && <p className="text-muted-foreground">{error.message}</p>}
        <Link href="/workspace/apps" className="text-primary underline">
          Back to Apps
        </Link>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "bg-background flex flex-col",
        full ? "fixed inset-0 z-50" : "h-full",
      )}
      data-testid="app-host"
      data-full={full ? "true" : "false"}
    >
      <header className="border-border flex min-h-12 flex-wrap items-center gap-x-3 gap-y-1 border-b px-3 py-1.5 text-sm md:px-4">
        <Link
          href="/workspace/apps"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 rounded-md max-md:min-h-11"
          aria-label="Back to Apps"
        >
          <ArrowLeftIcon className="size-4" />
          <span className="max-sm:hidden">Apps</span>
        </Link>
        <h1 className="min-w-0 truncate text-[15px] font-semibold">
          {app.name}
        </h1>
        <span className="text-muted-foreground text-xs">
          v{app.current_version}
        </span>
        <StatusWord tone={STATUS_TONE[app.status]} data-testid="app-status">
          {STATUS_WORDS[app.status]}
        </StatusWord>
        <span className="flex-1" />
        {app.status === "approved" && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setFull((f) => !f)}
            aria-pressed={full}
            data-testid="app-fullscreen"
            className="max-md:min-h-11"
          >
            {full ? <Minimize2Icon /> : <Maximize2Icon />}
            {full ? "Exit full screen" : "Full screen"}
          </Button>
        )}
      </header>
      {app.status === "approved" ? (
        <ApprovedApp app={app} takePrefetch={takePrefetch} />
      ) : (
        <AccessGate app={app} />
      )}
    </div>
  );
}

function ApprovedApp({
  app,
  takePrefetch,
}: {
  app: AppDetail;
  takePrefetch: () => Promise<BatchData> | null;
}) {
  const [connectFor, setConnectFor] = useState<string | null>(null);
  const [connected, setConnected] = useState<{
    source: string;
    at: number;
  } | null>(null);
  const { data: catalog } = useAppCatalog(connectFor !== null);
  const source = app.sources.find((s) => s.name === connectFor) ?? null;
  const entry = catalog?.find((e) => e.id === source?.use);
  const onConnect = useCallback((name: string) => setConnectFor(name), []);
  return (
    <>
      <AppFrame
        app={app}
        onConnect={onConnect}
        connected={connected}
        connectOpen={connectFor !== null}
        takePrefetch={takePrefetch}
      />
      <ConnectSheet
        source={source}
        entry={entry}
        onClose={() => setConnectFor(null)}
        onConnected={(name) => setConnected({ source: name, at: Date.now() })}
      />
    </>
  );
}

/** Needs approval, or access revoked: the card, never the frame. */
function AccessGate({ app }: { app: AppDetail }) {
  const { data: pending, isLoading } = usePendingApproval(
    app.id,
    app.approval === null,
  );
  const card = app.approval ?? pending ?? null;
  return (
    <div
      className="flex flex-1 flex-col items-center overflow-y-auto px-4 py-8"
      data-testid="app-access-gate"
    >
      <div className="flex w-full max-w-[640px] flex-col gap-4">
        <div className="flex items-start gap-3">
          <ShieldAlertIcon
            className="text-warning mt-0.5 size-5 shrink-0"
            aria-hidden
          />
          <div>
            <p className="text-[15px] font-semibold">
              {app.status === "revoked"
                ? "You revoked this app's access."
                : "This app needs your approval before it can show data."}
            </p>
            <p className="text-muted-foreground mt-1 text-sm">
              {app.status === "revoked"
                ? "It shows nothing until you approve it again."
                : "Check what it reads, then press Allow."}
            </p>
          </div>
        </div>
        {card ? (
          <AppApprovalCard
            card={card}
            heading={app.status === "revoked" ? "Approve again" : "App access"}
          />
        ) : (
          !isLoading && (
            <p className="text-muted-foreground text-sm">
              There is no approval waiting for this version. Ask for the app
              again in chat to raise one.
            </p>
          )
        )}
      </div>
    </div>
  );
}
