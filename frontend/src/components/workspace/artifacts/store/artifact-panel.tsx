"use client";

import {
  BookmarkIcon,
  CheckIcon,
  CodeIcon,
  DownloadIcon,
  EllipsisIcon,
  EyeIcon,
  HistoryIcon,
  MaximizeIcon,
  MessageCircleIcon,
  MoonIcon,
  PencilIcon,
  PinIcon,
  SparkleIcon,
  SunIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { atText } from "@/core/apps/wording";
import type { FrameTheme } from "@/core/artifacts/frame-host";
import {
  ArtifactsApiError,
  downloadUrl,
  EDITABLE_KINDS,
  isCodeKind,
  type ArtifactDetail,
} from "@/core/artifacts/store-api";
import {
  useArtifactActions,
  useArtifactVersion,
  useCodeActions,
  useSaveArtifact,
  useStoreArtifact,
} from "@/core/artifacts/store-hooks";
import {
  checkWords,
  confirmText,
  downloadForms,
  formatBytes,
  KIND_WORDS,
  originWords,
  refusalWords,
  sourceChip,
  titleText,
} from "@/core/artifacts/store-logic";
import { safeField } from "@/core/display/safe";
import { cn } from "@/lib/utils";

import { canRebuild, CodeKindView } from "./artifact-code-kind";
import { ArtifactContent, codeOf, KindIcon } from "./artifact-content";
import { VersionsDrawer } from "./artifact-versions";
import {
  ViewerHeader,
  AskBox,
  CheckChip,
  DeviceToggles,
  IconButton,
  iconButtonClass,
  PlainChip,
  SourceChip,
  Tip,
  useCanAsk,
  type Device,
} from "./viewer-parts";

/** Below this width the viewer is "compact" (a phone, or a narrow side
 * panel): Versions, Pin, Open chat and Full screen move into More. */
const COMPACT_PX = 600;

/** The viewer's own width (the side panel is narrower than the window). */
function useCompact(ref: React.RefObject<HTMLElement | null>) {
  const [compact, setCompact] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () =>
      setCompact(el.getBoundingClientRect().width < COMPACT_PX);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return compact;
}

/**
 * Spec 012: one artifact, in the chat's side panel (or over the chat at
 * phone width) and on the full page /workspace/artifacts/[id]. ONE header
 * row: the title (click or the pencil to rename), the version pill, the
 * save state, then icon buttons (Ask to change, Preview, Code, Download,
 * Versions, Pin, Open the chat that made it, More) and, at the far end,
 * Full screen and Close. A thin chip row (checks, source; preview sizes
 * for code that runs), the content, the versions drawer and a docked
 * "Ask for a change…" box. Buttons that do not apply are not shown.
 */
export function ArtifactPanel({
  id,
  version,
  onVersionChange,
  mode,
  onClose,
}: {
  id: string;
  version: number | null;
  onVersionChange: (n: number) => void;
  mode: "panel" | "page";
  onClose?: () => void;
}) {
  const { data, error, isLoading, refetch } = useStoreArtifact(id);

  if (isLoading) {
    return (
      <p className="text-muted-foreground p-4 text-sm" role="status">
        Loading…
      </p>
    );
  }
  if (error || !data) {
    const gone =
      error instanceof ArtifactsApiError &&
      (error.code === "artifact_not_found" || error.status === 404);
    return (
      <div className="flex flex-col gap-2 p-4" data-testid="artifact-missing">
        {onClose && (
          <IconButton
            label="Close"
            onClick={onClose}
            className="self-end"
            data-testid="artifact-close"
          >
            <XIcon />
          </IconButton>
        )}
        <p className="text-muted-foreground text-sm" role="status">
          {gone
            ? "This artifact isn't available."
            : "Couldn't load this artifact. Try again in a moment."}
        </p>
      </div>
    );
  }
  const shown =
    version && version >= 1 && version <= data.latest_version
      ? version
      : data.latest_version;
  return (
    <Viewer
      artifact={data}
      shown={shown}
      mode={mode}
      onClose={onClose}
      onVersionChange={onVersionChange}
      reload={async () => (await refetch()).data?.latest_version}
    />
  );
}

function Viewer({
  artifact,
  shown,
  mode,
  onClose,
  onVersionChange,
  reload,
}: {
  artifact: ArtifactDetail;
  shown: number;
  mode: "panel" | "page";
  onClose?: () => void;
  onVersionChange: (n: number) => void;
  reload: () => Promise<number | undefined>;
}) {
  const section = useRef<HTMLElement>(null);
  const compact = useCompact(section);
  const actions = useArtifactActions(artifact.id);
  const codeActions = useCodeActions(artifact.id);
  const canAsk = useCanAsk();
  const askInput = useRef<HTMLInputElement>(null);
  const previewBox = useRef<HTMLDivElement | null>(null);
  const drawerOpener = useRef<HTMLElement | null>(null);
  const keepFocus = useRef(false);

  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editingSource, setEditingSource] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [details, setDetails] = useState(false);
  const [tab, setTab] = useState<"preview" | "code">("preview");
  const [device, setDevice] = useState<Device>("desk");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  // The preview's own theme (never the app's): chosen per artifact, so it
  // falls back to the app theme when the viewer shows another artifact.
  const { resolvedTheme } = useTheme();
  const [themeChoice, setThemeChoice] = useState<{
    id: string;
    theme: FrameTheme;
  } | null>(null);
  if (themeChoice && themeChoice.id !== artifact.id) setThemeChoice(null);
  const previewTheme =
    themeChoice?.id === artifact.id ? themeChoice.theme : undefined;
  const shownTheme: FrameTheme =
    previewTheme ?? (resolvedTheme === "dark" ? "dark" : "light");

  const title = titleText(artifact.title);
  const v = artifact.versions.find((x) => x.n === shown);
  const code = isCodeKind(artifact.kind);
  const built = v?.code
    ? v.code.build_state === "ok"
    : !(
        artifact.code?.build_state === "build_failed" &&
        shown === artifact.latest_version
      );
  const forms = downloadForms(artifact.kind, built);
  const editable =
    EDITABLE_KINDS.includes(artifact.kind) &&
    !artifact.archived &&
    shown === artifact.latest_version;
  const rebuildable = canRebuild(artifact, shown);
  const fullscreen = code && tab === "preview" && built;
  const chatHref =
    artifact.origin_thread_id && !artifact.origin_deleted
      ? `/workspace/chats/${encodeURIComponent(artifact.origin_thread_id)}`
      : null;
  const fullHref = `/workspace/artifacts/${encodeURIComponent(artifact.id)}?v=${shown}`;

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMessage(null);
    try {
      await fn();
      setMessage({ ok: true, text: ok });
    } catch (err) {
      setMessage({ ok: false, text: refusalWords(err) });
    }
  };
  const view = (n: number) => {
    setEditing(false);
    setEditingSource(false);
    onVersionChange(n);
  };
  const toggleDrawer = (opener: HTMLElement | null) => {
    if (drawer) {
      setDrawer(false);
      drawerOpener.current?.focus();
    } else {
      drawerOpener.current = opener;
      setDrawer(true);
    }
  };
  const closeDrawer = () => {
    setDrawer(false);
    requestAnimationFrame(() => drawerOpener.current?.focus());
  };
  const togglePin = () =>
    void run(
      () => actions.patch.mutateAsync({ pinned: !artifact.pinned }),
      artifact.pinned ? "Unpinned." : "Pinned.",
    );
  const themeLabel =
    shownTheme === "dark" ? "Switch to light theme" : "Switch to dark theme";
  const toggleTheme = () =>
    setThemeChoice({
      id: artifact.id,
      theme: shownTheme === "dark" ? "light" : "dark",
    });
  const goFullscreen = () =>
    void previewBox.current?.requestFullscreen?.().catch(() => undefined);

  return (
    <section
      ref={section}
      className={cn(
        "bg-card flex w-full min-w-0 flex-col",
        mode === "panel" ? "h-full min-h-0" : "border-border rounded-xl border",
      )}
      data-testid="artifact-panel"
      data-artifact={artifact.id}
      data-version={shown}
      data-compact={compact ? "true" : "false"}
      aria-label={title}
    >
      <ViewerHeader data-testid="artifact-header">
        <KindIcon
          kind={artifact.kind}
          className="text-muted-foreground size-[18px] max-sm:hidden"
        />
        {renaming ? (
          <RenameInline
            initial={confirmText(artifact.title)}
            onCancel={() => setRenaming(false)}
            onSave={(t) => {
              setRenaming(false);
              if (t === confirmText(artifact.title)) return;
              void run(
                () => actions.patch.mutateAsync({ title: t }),
                "Renamed.",
              );
            }}
          />
        ) : (
          <div className="group ml-1 flex min-w-14 shrink items-center max-sm:ml-0">
            <h2
              className="cursor-text truncate text-base font-semibold"
              title={title}
              onClick={() => setRenaming(true)}
              data-testid="artifact-title"
            >
              {title}
            </h2>
            <IconButton
              label="Rename"
              onClick={() => setRenaming(true)}
              className="-ml-1 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 pointer-coarse:hidden [&_svg]:size-[13px]"
              data-testid="artifact-rename-pencil"
            >
              <PencilIcon />
            </IconButton>
          </div>
        )}
        {!compact && (
          <button
            type="button"
            onClick={(e) => toggleDrawer(e.currentTarget)}
            aria-expanded={drawer}
            aria-label={`Version ${shown} of ${artifact.latest_version}. Show versions`}
            className="border-border text-muted-foreground hover:text-foreground focus-visible:outline-primary h-[26px] shrink-0 cursor-pointer rounded-full border px-2 text-xs whitespace-nowrap focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:h-11"
            data-testid="artifact-version-label"
          >
            v{shown}
            {shown !== artifact.latest_version && (
              <span className="max-sm:hidden">
                {" "}
                (latest v{artifact.latest_version})
              </span>
            )}{" "}
            ▾
          </button>
        )}
        <SaveState artifact={artifact} compact={compact} />
        <span
          className="bg-border mx-1 h-5 w-px shrink-0 max-sm:hidden"
          aria-hidden
        />
        <div
          className={cn(
            "flex min-w-0 shrink-0 items-center",
            compact ? "gap-0.5" : "gap-1.5",
          )}
          role="toolbar"
          aria-label="Artifact actions"
        >
          {canAsk && (
            <IconButton
              label="Ask to change"
              primary
              onClick={() => askInput.current?.focus()}
              data-testid="artifact-ask-change"
            >
              <SparkleIcon />
            </IconButton>
          )}
          {code && (
            <>
              <IconButton
                label="Preview"
                pressed={tab === "preview"}
                onClick={() => setTab("preview")}
                data-testid="artifact-tab-preview"
              >
                <EyeIcon />
              </IconButton>
              <IconButton
                label="Code"
                pressed={tab === "code"}
                onClick={() => setTab("code")}
                data-testid="artifact-tab-code"
              >
                <CodeIcon />
              </IconButton>
            </>
          )}
          <DownloadControl
            artifactId={artifact.id}
            version={shown}
            forms={forms}
          />
          {!compact && (
            <>
              <IconButton
                label="Versions"
                tip="Versions · compare, restore"
                aria-expanded={drawer}
                onClick={(e) => toggleDrawer(e.currentTarget)}
                data-testid="artifact-versions-toggle"
              >
                <HistoryIcon />
              </IconButton>
              {!artifact.archived && (
                <IconButton
                  label="Pin to sidebar"
                  tip={
                    artifact.pinned
                      ? "Pinned to sidebar · click to unpin"
                      : "Pin to sidebar"
                  }
                  pressed={artifact.pinned}
                  disabled={actions.patch.isPending}
                  onClick={togglePin}
                  data-testid="artifact-pin"
                >
                  <PinIcon />
                </IconButton>
              )}
              {chatHref && (
                <Tip label="Open the chat that made it">
                  <Link
                    href={chatHref}
                    aria-label="Open the chat that made it"
                    className={iconButtonClass()}
                    data-testid="artifact-open-chat"
                  >
                    <MessageCircleIcon />
                  </Link>
                </Tip>
              )}
            </>
          )}
          <DropdownMenu>
            <Tip label="More · rename, duplicate, archive, details">
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label="More actions"
                  className={iconButtonClass()}
                  data-testid="artifact-more"
                >
                  <EllipsisIcon />
                </button>
              </DropdownMenuTrigger>
            </Tip>
            <DropdownMenuContent
              align="start"
              className="w-[220px] rounded-xl p-1.5"
              data-testid="artifact-more-menu"
              onCloseAutoFocus={(e) => {
                if (keepFocus.current) {
                  e.preventDefault();
                  keepFocus.current = false;
                }
              }}
            >
              {editable && !editing && !rebuildable && (
                <DropdownMenuItem
                  onSelect={() => {
                    setEditing(true);
                  }}
                  data-testid="artifact-edit"
                >
                  Edit
                </DropdownMenuItem>
              )}
              {rebuildable && !editingSource && (
                <DropdownMenuItem
                  onSelect={() => {
                    setTab("code");
                    setEditingSource(true);
                  }}
                  data-testid="artifact-edit-source"
                >
                  Edit source
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                onSelect={() => {
                  keepFocus.current = true;
                  setRenaming(true);
                }}
                data-testid="artifact-rename"
              >
                Rename
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={actions.duplicate.isPending}
                onSelect={() =>
                  void run(
                    () => actions.duplicate.mutateAsync(shown),
                    "Copied. The copy is in your Artifacts.",
                  )
                }
                data-testid="artifact-duplicate"
              >
                Duplicate
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={actions.archive.isPending}
                onSelect={() =>
                  void run(
                    () => actions.archive.mutateAsync(!artifact.archived),
                    artifact.archived
                      ? "Restored from the archive."
                      : "Archived.",
                  )
                }
                data-testid="artifact-archive"
              >
                {artifact.archived ? "Restore from archive" : "Archive"}
              </DropdownMenuItem>
              {artifact.archived && (
                <DropdownMenuItem
                  variant="destructive"
                  onSelect={() => setDeleting(true)}
                  data-testid="artifact-delete"
                >
                  Delete permanently
                </DropdownMenuItem>
              )}
              {compact && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onSelect={() => {
                      keepFocus.current = true;
                      drawerOpener.current = document.querySelector(
                        `[data-artifact="${artifact.id}"] [data-testid=artifact-more]`,
                      );
                      setDrawer(true);
                    }}
                    data-testid="artifact-versions-toggle"
                  >
                    Versions
                  </DropdownMenuItem>
                  {!artifact.archived && (
                    <DropdownMenuItem
                      disabled={actions.patch.isPending}
                      onSelect={togglePin}
                      data-testid="artifact-pin"
                    >
                      {artifact.pinned
                        ? "Unpin from sidebar"
                        : "Pin to sidebar"}
                    </DropdownMenuItem>
                  )}
                  {chatHref && (
                    <DropdownMenuItem asChild>
                      <Link href={chatHref} data-testid="artifact-open-chat">
                        Open the chat that made it
                      </Link>
                    </DropdownMenuItem>
                  )}
                  {fullscreen && (
                    <DropdownMenuItem
                      onSelect={toggleTheme}
                      data-testid="artifact-preview-theme"
                    >
                      {themeLabel}
                    </DropdownMenuItem>
                  )}
                  {fullscreen && (
                    <DropdownMenuItem
                      onSelect={goFullscreen}
                      data-testid="artifact-fullscreen"
                    >
                      Full screen
                    </DropdownMenuItem>
                  )}
                </>
              )}
              {mode === "panel" && (
                <DropdownMenuItem asChild>
                  <Link href={fullHref} data-testid="artifact-open-page">
                    Open full page
                  </Link>
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => setDetails(true)}
                className="text-muted-foreground"
                data-testid="artifact-details"
              >
                Details · checks, source, technical notes
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <span className="flex-1" />
        {fullscreen && !compact && (
          <IconButton
            label={themeLabel}
            onClick={toggleTheme}
            data-testid="artifact-preview-theme"
            data-theme={shownTheme}
          >
            {shownTheme === "dark" ? <SunIcon /> : <MoonIcon />}
          </IconButton>
        )}
        {fullscreen && !compact && (
          <IconButton
            label="Full screen"
            onClick={goFullscreen}
            data-testid="artifact-fullscreen"
          >
            <MaximizeIcon />
          </IconButton>
        )}
        {onClose && (
          <IconButton
            label="Close"
            onClick={onClose}
            data-testid="artifact-close"
          >
            <XIcon />
          </IconButton>
        )}
      </ViewerHeader>

      <div
        className="border-border flex min-w-0 shrink-0 flex-wrap items-center gap-2 border-b px-5 py-2.5 max-sm:px-3"
        data-testid="artifact-chips"
      >
        {code && v?.code?.build_state === "ok" && (
          <CheckChip
            check={v.code.check}
            findings={v.code.findings}
            pending={codeActions.checkAgain.isPending}
            onCheckAgain={() => codeActions.checkAgain.mutate(shown)}
          />
        )}
        {v && (
          <SourceChip
            kind={artifact.kind}
            lineage={v.lineage}
            source={v.lineage_source}
          />
        )}
        {artifact.origin_deleted && (
          <PlainChip testId="artifact-origin-deleted">
            From a chat you deleted
          </PlainChip>
        )}
        {artifact.archived && <PlainChip>Archived</PlainChip>}
        <span className="flex-1" />
        {code && tab === "preview" && built && (
          <DeviceToggles device={device} onChange={setDevice} />
        )}
      </div>
      {message && (
        <p
          role={message.ok ? "status" : "alert"}
          className={cn(
            "border-border border-b px-5 py-1.5 text-sm max-sm:px-3",
            message.ok ? "text-foreground" : "text-destructive",
          )}
          data-testid="artifact-message"
        >
          {message.text}
        </p>
      )}

      <div className={cn("flex min-w-0", mode === "panel" && "min-h-0 flex-1")}>
        <div
          className={cn(
            "bg-background flex min-w-0 flex-1 flex-col p-[22px] max-sm:p-3",
            mode === "panel" ? "min-h-0 overflow-auto" : "rounded-b-xl",
          )}
          data-testid="artifact-stage"
        >
          {editing ? (
            <ArtifactEditor
              artifact={artifact}
              onDone={(n) => {
                setEditing(false);
                if (n) onVersionChange(n);
              }}
              onReload={reload}
            />
          ) : code ? (
            <CodeKindView
              artifact={artifact}
              version={shown}
              onVersionChange={onVersionChange}
              tab={tab}
              device={device}
              editingSource={editingSource}
              onEditSourceDone={() => setEditingSource(false)}
              boxRef={previewBox}
              previewTheme={previewTheme}
            />
          ) : (
            <div className="border-border bg-card min-w-0 rounded-[14px] border p-5 max-sm:p-3">
              <ArtifactContent artifact={artifact} version={shown} />
            </div>
          )}
        </div>
        {drawer && !compact && (
          <VersionsDrawer
            artifact={artifact}
            shown={shown}
            onView={view}
            onClose={closeDrawer}
            asSheet={false}
          />
        )}
      </div>
      {drawer && compact && (
        <Sheet open onOpenChange={(o) => !o && closeDrawer()}>
          <SheetContent
            side="bottom"
            className="bg-card gap-0 rounded-t-xl p-0"
            onCloseAutoFocus={(e) => {
              e.preventDefault();
              drawerOpener.current?.focus();
            }}
          >
            <SheetTitle className="sr-only">Versions</SheetTitle>
            <SheetDescription className="sr-only">
              View, compare or restore a version.
            </SheetDescription>
            <VersionsDrawer
              artifact={artifact}
              shown={shown}
              onView={view}
              onClose={closeDrawer}
              asSheet
            />
          </SheetContent>
        </Sheet>
      )}
      {canAsk && (
        <AskBox ref={askInput} artifactId={artifact.id} version={shown} />
      )}
      {details && (
        <DetailsDialog
          artifact={artifact}
          shown={shown}
          onClose={() => setDetails(false)}
        />
      )}
      {deleting && (
        <DeleteDialog artifact={artifact} onClose={() => setDeleting(false)} />
      )}
    </section>
  );
}

/** Inline rename: Enter or leaving the field saves, Escape cancels. The
 * same rule as before: 1 to 120 characters after trimming. */
function RenameInline({
  initial,
  onSave,
  onCancel,
}: {
  initial: string;
  onSave: (title: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const done = useRef(false);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);
  const finish = (save: boolean) => {
    if (done.current) return;
    done.current = true;
    const t = value.trim();
    if (save && t && t.length <= 120) onSave(t);
    else onCancel();
  };
  return (
    <Input
      ref={ref}
      value={value}
      maxLength={120}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          finish(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          finish(false);
        }
      }}
      onBlur={() => finish(true)}
      aria-label="Title"
      className="ml-1 h-8 min-w-0 flex-[0_1_320px] text-base font-semibold"
      data-testid="artifact-rename-input"
    />
  );
}

/** "✓ Saved" (its menu offers Unsave) or "Save", in the same spot; the
 * existing optimistic save with its rollback. */
function SaveState({
  artifact,
  compact,
}: {
  artifact: ArtifactDetail;
  compact: boolean;
}) {
  const save = useSaveArtifact(artifact.id);
  const saved = save.isPending
    ? save.variables
    : save.isSuccess
      ? save.data.saved
      : artifact.saved;
  const cls =
    "focus-visible:outline-primary inline-flex h-[26px] shrink-0 cursor-pointer items-center gap-1 rounded-full px-1.5 text-xs whitespace-nowrap focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:h-11";
  return (
    <div className="flex shrink-0 items-center gap-1">
      {saved ? (
        <DropdownMenu>
          <Tip label="Saved · click to unsave">
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={cn(cls, "text-success hover:bg-surface-raised")}
                aria-label="Saved. More options"
                data-testid="artifact-store-saved"
              >
                <CheckIcon
                  className="size-[13px]"
                  strokeWidth={2.5}
                  aria-hidden
                />
                <span className={cn(compact && "sr-only")}>Saved</span>
              </button>
            </DropdownMenuTrigger>
          </Tip>
          <DropdownMenuContent align="start">
            <DropdownMenuItem
              onSelect={() => save.mutate(false)}
              data-testid="artifact-store-unsave"
            >
              Unsave
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <Tip label="Save to your Artifacts">
          <button
            type="button"
            className={cn(
              cls,
              "border-border text-foreground hover:bg-surface-raised border px-2",
            )}
            disabled={save.isPending}
            onClick={() => save.mutate(true)}
            data-testid="artifact-store-save"
          >
            <BookmarkIcon className="size-[13px]" aria-hidden />
            <span className={cn(compact && "sr-only")}>Save</span>
          </button>
        </Tip>
      )}
      {save.isError && (
        <span role="alert" className="text-destructive text-xs max-sm:sr-only">
          {refusalWords(save.error)}
        </span>
      )}
    </div>
  );
}

/** Download: one form downloads at once; several open a menu of exactly the
 * forms the download route offers for this kind. */
function DownloadControl({
  artifactId,
  version,
  forms,
}: {
  artifactId: string;
  version: number;
  forms: ReturnType<typeof downloadForms>;
}) {
  if (forms.length === 0) return null;
  if (forms.length === 1) {
    const f = forms[0]!;
    const label = f.label === "Download" ? "Download" : `Download · ${f.label}`;
    return (
      <Tip label={label}>
        <a
          href={downloadUrl(artifactId, version, f.form)}
          download
          aria-label="Download"
          className={iconButtonClass()}
          data-testid="artifact-download"
          data-form={f.form}
        >
          <DownloadIcon />
        </a>
      </Tip>
    );
  }
  return (
    <DropdownMenu>
      <Tip label={`Download · ${forms.map((f) => f.label).join(", ")}`}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label="Download"
            className={iconButtonClass()}
            data-testid="artifact-download-menu"
          >
            <DownloadIcon />
          </button>
        </DropdownMenuTrigger>
      </Tip>
      <DropdownMenuContent align="start" data-testid="artifact-download-list">
        {forms.map((f) => (
          <DropdownMenuItem key={f.form} asChild>
            <a
              href={downloadUrl(artifactId, version, f.form)}
              download
              data-testid="artifact-download-form"
              data-form={f.form}
            >
              {f.label}
            </a>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** More → Details: the technical bits the header no longer shows. */
function DetailsDialog({
  artifact,
  shown,
  onClose,
}: {
  artifact: ArtifactDetail;
  shown: number;
  onClose: () => void;
}) {
  const v = artifact.versions.find((x) => x.n === shown);
  const note = safeField(v?.note);
  const check = v?.code?.check;
  const failures = check?.failures ?? [];
  const findings = v?.code?.findings ?? [];
  const rows: [string, string][] = [
    ["Kind", KIND_WORDS[artifact.kind]],
    ["Version", `${shown} of ${artifact.latest_version}`],
    ["Made", `${v ? originWords(v.origin) : ""} · ${atText(v?.created_at)}`],
    ["Size", formatBytes(v?.size ?? artifact.size)],
    ["Type", safeField(v?.media_type ?? artifact.media_type)],
    [
      "Source",
      v ? sourceChip(artifact.kind, v.lineage, v.lineage_source).label : "",
    ],
  ];
  if (artifact.origin_deleted) rows.push(["Chat", "From a chat you deleted"]);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="artifact-details-dialog">
        <DialogHeader>
          <DialogTitle>Details</DialogTitle>
          <DialogDescription className="break-all">
            {titleText(artifact.title)}
          </DialogDescription>
        </DialogHeader>
        {note && (
          <p className="text-sm">
            <span className="font-medium">The assistant&rsquo;s note:</span>{" "}
            <span data-testid="artifact-note">{note}</span>
          </p>
        )}
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {rows.map(([k, val]) => (
            <div key={k} className="contents">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="min-w-0 break-words">{val}</dd>
            </div>
          ))}
        </dl>
        {v?.code && (
          <div className="flex flex-col gap-1 text-sm">
            <p className="font-medium">Checks</p>
            <p>
              {v.code.build_state === "build_failed"
                ? "This version did not build."
                : checkWords(check?.state, check?.summary).label}
            </p>
            {(failures.length > 0 || findings.length > 0) && (
              <ul className="text-muted-foreground list-disc pl-5 text-xs">
                {failures.map((f, i) => (
                  <li key={`f${i}`}>{safeField(f)}</li>
                ))}
                {findings.map((f, i) => (
                  <li key={`s${i}`}>{safeField(f)}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ArtifactEditor({
  artifact,
  onDone,
  onReload,
}: {
  artifact: ArtifactDetail;
  onDone: (newVersion?: number) => void;
  onReload: () => Promise<number | undefined>;
}) {
  const base = artifact.latest_version;
  const { data, isLoading } = useArtifactVersion(artifact.id, base);
  const actions = useArtifactActions(artifact.id);
  const [draft, setDraft] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState(base);
  const code = artifact.kind === "code" ? codeOf(data?.content) : null;
  const original =
    code?.text ?? (typeof data?.content === "string" ? data.content : "");
  const value = draft ?? original;
  const dirty = draft !== null && draft !== original;

  // Leaving with unsaved edits asks first (the browser's own prompt).
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (isLoading || !data) {
    return (
      <p className="text-muted-foreground text-sm" role="status">
        Loading…
      </p>
    );
  }
  const save = async () => {
    setError(null);
    try {
      const r = await actions.save.mutateAsync({
        base_version: opened,
        content: value,
        ...(code ? { language: code.language } : {}),
      });
      onDone(r.version.n);
    } catch (err) {
      if (
        err instanceof ArtifactsApiError &&
        err.code === "stale_base_version"
      ) {
        setStale(true);
      } else {
        setError(refusalWords(err));
      }
    }
  };
  return (
    <div className="flex flex-col gap-2" data-testid="artifact-editor">
      <label className="text-muted-foreground text-xs" htmlFor="artifact-draft">
        Editing version {opened}. Saving makes a new version.
      </label>
      <Textarea
        id="artifact-draft"
        value={value}
        onChange={(e) => setDraft(e.target.value)}
        spellCheck={artifact.kind === "markdown"}
        className="min-h-64 font-mono text-sm"
        data-testid="artifact-draft"
      />
      {stale && (
        <div
          role="alert"
          className="border-warning/50 flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm"
          data-testid="artifact-stale"
        >
          <span>
            A newer version exists. Reload to see it; your text stays here.
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() =>
              void onReload().then((latest) => {
                setStale(false);
                if (latest) setOpened(latest);
              })
            }
            data-testid="artifact-stale-reload"
          >
            Reload
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          disabled={!dirty || actions.save.isPending || stale}
          onClick={() => void save()}
          data-testid="artifact-save"
        >
          Save as a new version
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => onDone()}
          data-testid="artifact-edit-cancel"
        >
          {dirty ? "Discard changes" : "Cancel"}
        </Button>
      </div>
    </div>
  );
}

function DeleteDialog({
  artifact,
  onClose,
}: {
  artifact: ArtifactDetail;
  onClose: () => void;
}) {
  const actions = useArtifactActions(artifact.id);
  const title = titleText(artifact.title);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const expected = confirmText(artifact.title);
  const matches = confirmText(typed) === expected && expected !== "";
  const confirm = async () => {
    setError(null);
    try {
      await actions.remove.mutateAsync(artifact.version_count);
      setDone(true);
    } catch (err) {
      setError(refusalWords(err));
    }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="artifact-delete-dialog">
        <DialogHeader>
          <DialogTitle>Delete permanently?</DialogTitle>
          <DialogDescription>
            This removes &ldquo;
            <span className="break-all">{title}</span>&rdquo; and all{" "}
            {artifact.version_count}{" "}
            {artifact.version_count === 1 ? "version" : "versions"}. It
            can&rsquo;t be undone.
          </DialogDescription>
        </DialogHeader>
        {done ? (
          <p role="status" className="text-sm">
            Deleted.{" "}
            <Link
              href="/workspace/artifacts"
              className="text-primary underline"
            >
              Back to Artifacts
            </Link>
          </p>
        ) : (
          <>
            <p className="text-sm">Type the title to confirm:</p>
            <code
              className="bg-muted block rounded-md px-2 py-1 font-mono text-sm break-all select-all"
              data-testid="artifact-delete-title"
            >
              {expected}
            </code>
            <label className="sr-only" htmlFor="artifact-delete-confirm">
              Title
            </label>
            <Input
              id="artifact-delete-confirm"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoComplete="off"
              data-testid="artifact-delete-input"
            />
            {error && (
              <p role="alert" className="text-destructive text-sm">
                {error}
              </p>
            )}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={onClose}>
                Keep it
              </Button>
              <Button
                type="button"
                variant="destructive"
                disabled={!matches || actions.remove.isPending}
                onClick={() => void confirm()}
                data-testid="artifact-delete-confirm"
              >
                Delete permanently
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
