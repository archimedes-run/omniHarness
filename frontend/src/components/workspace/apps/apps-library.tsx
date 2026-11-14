"use client";

import {
  ChevronDownIcon,
  ExternalLinkIcon,
  LayoutGridIcon,
  PinIcon,
  PinOffIcon,
  RotateCcwIcon,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AppApprovalCard } from "@/components/workspace/confirmations/app-approval-card";
import {
  PageColumn,
  PageHeader,
  RowList,
  StatusWord,
} from "@/components/workspace/page-kit";
import { AppsApiError, type AppSummary } from "@/core/apps/api";
import {
  useAppPermissions,
  useAppPins,
  useApps,
  useAppVersions,
  usePendingApproval,
  useRestoreApp,
  useRevokeApp,
  useSaveAppPins,
} from "@/core/apps/hooks";
import {
  activityWords,
  ago,
  atText,
  lastStateWords,
  STATUS_TONE,
  STATUS_WORDS,
  versionChanged,
  versionSource,
  writeError,
} from "@/core/apps/wording";
import { cn } from "@/lib/utils";

type Panel = "history" | "permissions" | "approval" | null;

/**
 * Spec 011 US3, FR-029, FR-030: the Apps library. Each app: name, version,
 * status, when it was last opened, Open, Pin to sidebar, History (versions
 * with Restore, which writes a NEW version), Permissions (each approved
 * source in the gateway's words, when it was granted, Revoke). An app that
 * needs approval shows its App access card here too (button only).
 */
export function AppsLibrary() {
  const { apps, error, isLoading } = useApps();
  const { pins } = useAppPins();
  return (
    <PageColumn>
      <PageHeader
        title="Apps"
        description="Small pages that show your own data. They never touch the network or hold a token, and the assistant never sees what they show."
      />
      {isLoading ? (
        <Skeleton className="h-32 rounded-xl" />
      ) : error ? (
        <p className="text-destructive" role="alert">
          Couldn&rsquo;t load your apps. Try again in a moment.
        </p>
      ) : !apps || apps.length === 0 ? (
        <div
          className="bg-card border-border flex flex-col items-start gap-2 rounded-xl border px-[18px] py-6"
          data-testid="apps-empty"
        >
          <LayoutGridIcon
            className="text-muted-foreground size-5"
            aria-hidden
          />
          <p className="font-medium">No apps yet</p>
          <p className="text-muted-foreground">
            Ask for one in any chat, for example &ldquo;build me a Today page
            with my calendar and the PRs waiting on me&rdquo;.
          </p>
        </div>
      ) : (
        <RowList data-testid="apps-list">
          {apps.map((app) => (
            <AppRow key={app.id} app={app} pins={pins} />
          ))}
        </RowList>
      )}
    </PageColumn>
  );
}

function AppRow({
  app,
  pins,
}: {
  app: AppSummary;
  pins: string[] | undefined;
}) {
  const [panel, setPanel] = useState<Panel>(null);
  const savePins = useSaveAppPins();
  const pinned = pins ? pins.includes(app.id) : app.pinned;
  const toggle = (p: Exclude<Panel, null>) =>
    setPanel((cur) => (cur === p ? null : p));

  const onPin = () => {
    const current = pins ?? [];
    const next = pinned
      ? current.filter((id) => id !== app.id)
      : [...current.filter((id) => id !== app.id), app.id];
    savePins.mutate(next);
  };

  const panelId = `app-panel-${app.id}`;
  return (
    <li className="px-[18px] py-3.5" data-testid="app-row" data-app={app.id}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="min-w-0 flex-[1_1_240px]">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <Link
              href={`/workspace/apps/${encodeURIComponent(app.id)}`}
              className="truncate text-[15px] font-semibold hover:underline"
            >
              {app.name}
            </Link>
            <span className="text-muted-foreground text-xs">
              v{app.current_version}
            </span>
            {app.pending_version != null && (
              <span
                className="text-warning text-xs"
                data-testid="app-row-pending"
              >
                v{app.pending_version} waiting for approval
              </span>
            )}
            <StatusWord
              tone={STATUS_TONE[app.status]}
              data-testid="app-row-status"
            >
              {STATUS_WORDS[app.status]}
            </StatusWord>
            {pinned && (
              <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
                <PinIcon className="size-3" aria-hidden />
                Pinned
              </span>
            )}
          </div>
          {app.description && (
            <p className="text-muted-foreground mt-0.5 line-clamp-2 text-sm">
              {app.description}
            </p>
          )}
          <p className="text-muted-foreground mt-0.5 text-xs">
            {app.last_opened_at
              ? `Last opened ${ago(app.last_opened_at)}`
              : "Never opened"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Button asChild size="sm" className="max-md:min-h-11">
            <Link href={`/workspace/apps/${encodeURIComponent(app.id)}`}>
              <ExternalLinkIcon />
              Open
            </Link>
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onPin}
            disabled={savePins.isPending}
            aria-pressed={pinned}
            data-testid="app-pin"
            className="max-md:min-h-11"
          >
            {pinned ? <PinOffIcon /> : <PinIcon />}
            {pinned ? "Unpin" : "Pin to sidebar"}
          </Button>
          {(app.status !== "approved" || app.pending_version != null) && (
            <PanelButton
              open={panel === "approval"}
              controls={panelId}
              onClick={() => toggle("approval")}
              testId="app-review"
            >
              {app.status === "revoked" ? "Approve again" : "Review access"}
            </PanelButton>
          )}
          <PanelButton
            open={panel === "history"}
            controls={panelId}
            onClick={() => toggle("history")}
            testId="app-history"
          >
            History
          </PanelButton>
          <PanelButton
            open={panel === "permissions"}
            controls={panelId}
            onClick={() => toggle("permissions")}
            testId="app-permissions"
          >
            Permissions
          </PanelButton>
        </div>
      </div>
      {savePins.error && (
        <p className="text-destructive mt-2 text-xs" role="alert">
          Could not save your pins: {savePins.error.message}
        </p>
      )}
      <div id={panelId}>
        {panel === "history" && <HistoryPanel appId={app.id} />}
        {panel === "permissions" && <PermissionsPanel appId={app.id} />}
        {panel === "approval" && <ApprovalPanel app={app} />}
      </div>
    </li>
  );
}

function PanelButton({
  open,
  controls,
  onClick,
  testId,
  children,
}: {
  open: boolean;
  controls: string;
  onClick: () => void;
  testId: string;
  children: React.ReactNode;
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant="ghost"
      onClick={onClick}
      aria-expanded={open}
      aria-controls={controls}
      data-testid={testId}
      className="max-md:min-h-11"
    >
      {children}
      <ChevronDownIcon
        className={cn("transition-transform", open && "rotate-180")}
      />
    </Button>
  );
}

function HistoryPanel({ appId }: { appId: string }) {
  const { data, error, isLoading, refetch } = useAppVersions(appId, true);
  const restore = useRestoreApp();
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );

  const run = async (toVersion: number) => {
    if (!data) return;
    setMessage(null);
    try {
      const app = await restore.mutateAsync({
        id: appId,
        toVersion,
        baseVersion: data.current,
      });
      setMessage({
        ok: true,
        text:
          `Restored version ${toVersion} as version ${app.current_version}.` +
          (app.status === "needs_approval"
            ? " It reads different data, so it needs your approval."
            : ""),
      });
    } catch (err) {
      const code = err instanceof AppsApiError ? err.code : "error";
      setMessage({
        ok: false,
        text: writeError(
          code,
          err instanceof Error ? err.message : String(err),
        ),
      });
      if (code === "stale_version") void refetch();
    }
  };

  if (isLoading) return <Skeleton className="mt-3 h-20 rounded-lg" />;
  if (error || !data) {
    return (
      <p className="text-destructive mt-3 text-sm" role="alert">
        Could not read the history: {error?.message}
      </p>
    );
  }
  return (
    <div className="mt-3" data-testid="app-history-panel">
      <ol className="border-border divide-border divide-y rounded-lg border">
        {data.versions.map((v) => {
          const current = v.version === data.current;
          return (
            <li
              key={v.version}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5"
              data-version={v.version}
            >
              <span className="w-10 font-medium tabular-nums">
                v{v.version}
              </span>
              <div className="min-w-0 flex-[1_1_220px]">
                <p>
                  {versionSource(v)}
                  <span className="text-muted-foreground">
                    {" · "}
                    {atText(v.at)}
                  </span>
                </p>
                <p className="text-muted-foreground text-xs">
                  {versionChanged(v)}
                  {" · "}
                  {v.approved ? "Access approved" : "Not approved"}
                </p>
              </div>
              {current ? (
                <span className="text-muted-foreground text-xs">Current</span>
              ) : (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={restore.isPending}
                  onClick={() => void run(v.version)}
                  data-testid="app-restore"
                  className="max-md:min-h-11"
                >
                  <RotateCcwIcon />
                  Restore
                </Button>
              )}
            </li>
          );
        })}
      </ol>
      <p className="text-muted-foreground mt-2 text-xs">
        Restore makes a new version with that version&rsquo;s content; nothing
        is deleted.
      </p>
      {message && (
        <p
          role={message.ok ? "status" : "alert"}
          className={cn(
            "mt-2 text-sm",
            message.ok ? "text-foreground" : "text-destructive",
          )}
        >
          {message.text}
        </p>
      )}
    </div>
  );
}

function PermissionsPanel({ appId }: { appId: string }) {
  const { data, error, isLoading } = useAppPermissions(appId, true);
  const revoke = useRevokeApp();
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  if (isLoading) return <Skeleton className="mt-3 h-20 rounded-lg" />;
  if (error || !data) {
    return (
      <p className="text-destructive mt-3 text-sm" role="alert">
        Could not read the permissions: {error?.message}
      </p>
    );
  }
  const active = data.grants.find((g) => g.revoked_at === null);
  const onRevoke = async () => {
    setMessage(null);
    try {
      await revoke.mutateAsync(appId);
      setConfirming(false);
      setMessage(
        "Access revoked. The app shows nothing until you approve it again.",
      );
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  };
  return (
    <div
      className="mt-3 flex flex-col gap-3"
      data-testid="app-permissions-panel"
    >
      <p className="text-sm">
        {data.status === "approved" && active
          ? `Approved ${atText(active.approved_at)}. This app may:`
          : data.status === "revoked"
            ? "Access revoked. When approved, this app reads:"
            : "Not approved yet. When approved, this app reads:"}
      </p>
      <ul className="border-border divide-border divide-y rounded-lg border">
        {data.sources.map((s) => (
          <li key={s.name} className="px-3 py-2.5" data-source={s.name}>
            <p className="break-words">{s.words}</p>
            <p className="text-muted-foreground mt-0.5 text-xs">
              {s.refresh_words}
              {" · "}
              {lastStateWords(s.last_state, s.last_fetched_at, s.last_error)}
            </p>
          </li>
        ))}
      </ul>
      <p className="text-muted-foreground text-xs">{data.sentence}</p>
      {data.grants.length > 0 && (
        <details className="text-xs">
          <summary className="text-muted-foreground cursor-pointer">
            Grant history ({data.grants.length})
          </summary>
          <ul className="mt-1 flex flex-col gap-1">
            {data.grants.map((g) => (
              <li key={`${g.manifest_hash}-${g.approved_at}`}>
                Granted {atText(g.approved_at)}
                {g.version != null && ` for version ${g.version}`}
                {g.revoked_at
                  ? `, revoked ${atText(g.revoked_at)}`
                  : ", active"}
              </li>
            ))}
          </ul>
        </details>
      )}
      {data.activity && data.activity.length > 0 && (
        <details className="text-xs" data-testid="app-activity">
          <summary className="text-muted-foreground cursor-pointer">
            Recent activity ({data.activity.length})
          </summary>
          <ul className="mt-1 flex flex-col gap-1">
            {data.activity.map((a, n) => (
              <li key={`${a.at}-${n}`}>
                {atText(a.at)}: {activityWords(a)}
              </li>
            ))}
          </ul>
        </details>
      )}
      {data.status === "approved" && (
        <div className="flex flex-wrap items-center gap-2">
          {confirming ? (
            <>
              <span className="text-sm">
                Revoke every grant of this app now?
              </span>
              <Button
                type="button"
                size="sm"
                variant="destructive"
                disabled={revoke.isPending}
                onClick={() => void onRevoke()}
                data-testid="app-revoke-confirm"
                className="max-md:min-h-11"
              >
                Revoke
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setConfirming(false)}
                className="max-md:min-h-11"
              >
                Keep access
              </Button>
            </>
          ) : (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setConfirming(true)}
              data-testid="app-revoke"
              className="max-md:min-h-11"
            >
              Revoke access
            </Button>
          )}
        </div>
      )}
      {message && (
        <p role="status" className="text-sm">
          {message}
        </p>
      )}
    </div>
  );
}

function ApprovalPanel({ app }: { app: AppSummary }) {
  const { data, error, isLoading } = usePendingApproval(app.id, true);
  if (isLoading) return <Skeleton className="mt-3 h-24 rounded-lg" />;
  if (error) {
    return (
      <p className="text-destructive mt-3 text-sm" role="alert">
        Could not read the approval: {error.message}
      </p>
    );
  }
  if (!data) {
    return (
      <p className="text-muted-foreground mt-3 text-sm">
        There is no approval waiting for this version. Ask for the app again in
        chat to raise one.
      </p>
    );
  }
  return (
    <div className="mt-3">
      <AppApprovalCard
        card={data}
        heading={app.status === "revoked" ? "Approve again" : "App access"}
      />
    </div>
  );
}
