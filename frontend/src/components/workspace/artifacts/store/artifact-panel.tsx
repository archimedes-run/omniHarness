"use client";

import {
  ArchiveIcon,
  ArchiveRestoreIcon,
  CopyIcon,
  ExternalLinkIcon,
  HistoryIcon,
  MessageSquareIcon,
  PencilIcon,
  PinIcon,
  PinOffIcon,
  RotateCcwIcon,
  Trash2Icon,
  TypeIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { atText } from "@/core/apps/wording";
import {
  ArtifactsApiError,
  EDITABLE_KINDS,
  type ArtifactDetail,
  type ArtifactVersion,
} from "@/core/artifacts/store-api";
import {
  useArtifactActions,
  useArtifactVersion,
  useStoreArtifact,
} from "@/core/artifacts/store-hooks";
import {
  KIND_WORDS,
  lineageWords,
  originWords,
  refusalWords,
  titleText,
} from "@/core/artifacts/store-logic";
import { safeField } from "@/core/display/safe";
import { cn } from "@/lib/utils";

import { ArtifactContent, codeOf, KindIcon } from "./artifact-content";

/**
 * Spec 012 Slice 1: one artifact, in the chat's side panel or full page at
 * /workspace/artifacts/[id]. Shows the chosen version; Versions lists them
 * all (View, "Restore this version", which makes a NEW version); the owner
 * edits markdown, code and mermaid in a plain editor (a new version on the
 * base it was opened from; a stale base says "A newer version exists");
 * Rename, Pin, Duplicate, Archive; Delete permanently only when archived,
 * after typing the title.
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
  const [showVersions, setShowVersions] = useState(false);
  const [editing, setEditing] = useState(false);

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
        <PanelClose onClose={onClose} />
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
    <section
      className={cn(
        "flex min-h-0 w-full min-w-0 flex-col gap-3",
        mode === "panel" ? "h-full" : "",
      )}
      data-testid="artifact-panel"
      data-artifact={data.id}
      data-version={shown}
      aria-label={titleText(data.title)}
    >
      <PanelHeader
        artifact={data}
        shown={shown}
        mode={mode}
        onClose={onClose}
        showVersions={showVersions}
        onToggleVersions={() => setShowVersions((v) => !v)}
        onEdit={() => setEditing(true)}
        editing={editing}
      />
      {showVersions && (
        <VersionList
          artifact={data}
          shown={shown}
          onView={(n) => {
            setEditing(false);
            onVersionChange(n);
          }}
        />
      )}
      <div
        className={cn(
          "min-h-0 min-w-0",
          mode === "panel" ? "flex-1 overflow-auto" : "",
        )}
      >
        {editing ? (
          <ArtifactEditor
            artifact={data}
            onDone={(n) => {
              setEditing(false);
              if (n) onVersionChange(n);
            }}
            onReload={async () => (await refetch()).data?.latest_version}
          />
        ) : (
          <ArtifactContent artifact={data} version={shown} />
        )}
      </div>
    </section>
  );
}

function PanelClose({ onClose }: { onClose?: () => void }) {
  if (!onClose) return null;
  return (
    <Button
      size="icon-sm"
      variant="ghost"
      onClick={onClose}
      aria-label="Close"
      className="self-end max-md:size-11"
    >
      <XIcon />
    </Button>
  );
}

function PanelHeader({
  artifact,
  shown,
  mode,
  onClose,
  showVersions,
  onToggleVersions,
  onEdit,
  editing,
}: {
  artifact: ArtifactDetail;
  shown: number;
  mode: "panel" | "page";
  onClose?: () => void;
  showVersions: boolean;
  onToggleVersions: () => void;
  onEdit: () => void;
  editing: boolean;
}) {
  const actions = useArtifactActions(artifact.id);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const title = titleText(artifact.title);
  const v = artifact.versions.find((x) => x.n === shown);
  const lineage = v ? lineageWords(v.lineage, v.lineage_source) : null;
  const note = safeField(v?.note);
  const editable =
    EDITABLE_KINDS.includes(artifact.kind) &&
    !artifact.archived &&
    shown === artifact.latest_version;

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMessage(null);
    try {
      await fn();
      setMessage({ ok: true, text: ok });
    } catch (err) {
      setMessage({ ok: false, text: refusalWords(err) });
    }
  };

  return (
    <header className="flex min-w-0 flex-col gap-2">
      <div className="flex min-w-0 items-start gap-2">
        <KindIcon kind={artifact.kind} className="mt-1" />
        <div className="min-w-0 flex-1">
          {renaming ? (
            <RenameForm
              initial={title}
              pending={actions.patch.isPending}
              onCancel={() => setRenaming(false)}
              onSave={(t) =>
                void run(async () => {
                  await actions.patch.mutateAsync({ title: t });
                  setRenaming(false);
                }, "Renamed.")
              }
            />
          ) : (
            <h2
              className="truncate text-base font-semibold"
              title={title}
              data-testid="artifact-title"
            >
              {title}
            </h2>
          )}
          <p className="text-muted-foreground flex flex-wrap gap-x-2 text-xs">
            <span>{KIND_WORDS[artifact.kind]}</span>
            <span data-testid="artifact-version-label">
              Version {shown}
              {shown !== artifact.latest_version &&
                ` (latest: ${artifact.latest_version})`}
            </span>
            {artifact.pinned && <span>Pinned</span>}
            {artifact.archived && (
              <span className="text-warning">Archived</span>
            )}
          </p>
        </div>
        {mode === "panel" && (
          <Button
            asChild
            size="icon-sm"
            variant="ghost"
            className="max-md:size-11"
          >
            <Link
              href={`/workspace/artifacts/${encodeURIComponent(artifact.id)}?v=${shown}`}
              aria-label="Open full page"
              title="Open full page"
            >
              <ExternalLinkIcon />
            </Link>
          </Button>
        )}
        <PanelClose onClose={onClose} />
      </div>
      {lineage && (
        <p
          className="border-warning/40 text-foreground w-fit rounded-md border px-2 py-0.5 text-xs"
          data-testid="artifact-lineage"
        >
          {lineage}
        </p>
      )}
      {note && (
        <p className="text-muted-foreground text-xs">
          <span className="font-medium">The assistant&rsquo;s note:</span>{" "}
          <span data-testid="artifact-note">{note}</span>
        </p>
      )}
      <div className="flex flex-wrap gap-1.5">
        <Button
          type="button"
          size="sm"
          variant={showVersions ? "secondary" : "outline"}
          aria-expanded={showVersions}
          onClick={onToggleVersions}
          data-testid="artifact-versions-toggle"
          className="max-md:min-h-11"
        >
          <HistoryIcon />
          Versions ({artifact.version_count})
        </Button>
        {editable && !editing && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onEdit}
            data-testid="artifact-edit"
            className="max-md:min-h-11"
          >
            <PencilIcon />
            Edit
          </Button>
        )}
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setRenaming(true)}
          data-testid="artifact-rename"
          className="max-md:min-h-11"
        >
          <TypeIcon />
          Rename
        </Button>
        {!artifact.archived && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            aria-pressed={artifact.pinned}
            disabled={actions.patch.isPending}
            onClick={() =>
              void run(
                () => actions.patch.mutateAsync({ pinned: !artifact.pinned }),
                artifact.pinned ? "Unpinned." : "Pinned.",
              )
            }
            data-testid="artifact-pin"
            className="max-md:min-h-11"
          >
            {artifact.pinned ? <PinOffIcon /> : <PinIcon />}
            {artifact.pinned ? "Unpin" : "Pin"}
          </Button>
        )}
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={actions.duplicate.isPending}
          onClick={() =>
            void run(
              () => actions.duplicate.mutateAsync(shown),
              "Copied. The copy is in your Artifacts.",
            )
          }
          data-testid="artifact-duplicate"
          className="max-md:min-h-11"
        >
          <CopyIcon />
          Duplicate
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={actions.archive.isPending}
          onClick={() =>
            void run(
              () => actions.archive.mutateAsync(!artifact.archived),
              artifact.archived ? "Restored from the archive." : "Archived.",
            )
          }
          data-testid="artifact-archive"
          className="max-md:min-h-11"
        >
          {artifact.archived ? <ArchiveRestoreIcon /> : <ArchiveIcon />}
          {artifact.archived ? "Restore from archive" : "Archive"}
        </Button>
        {artifact.archived && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="text-destructive max-md:min-h-11"
            onClick={() => setDeleting(true)}
            data-testid="artifact-delete"
          >
            <Trash2Icon />
            Delete permanently
          </Button>
        )}
        {artifact.origin_thread_id && (
          <Button asChild size="sm" variant="ghost" className="max-md:min-h-11">
            <Link
              href={`/workspace/chats/${encodeURIComponent(artifact.origin_thread_id)}`}
              data-testid="artifact-open-chat"
            >
              <MessageSquareIcon />
              Open the chat that made it
            </Link>
          </Button>
        )}
      </div>
      {message && (
        <p
          role={message.ok ? "status" : "alert"}
          className={cn(
            "text-sm",
            message.ok ? "text-foreground" : "text-destructive",
          )}
        >
          {message.text}
        </p>
      )}
      {deleting && (
        <DeleteDialog artifact={artifact} onClose={() => setDeleting(false)} />
      )}
    </header>
  );
}

function RenameForm({
  initial,
  pending,
  onSave,
  onCancel,
}: {
  initial: string;
  pending: boolean;
  onSave: (title: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const trimmed = value.trim();
  return (
    <form
      className="flex flex-wrap items-center gap-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (trimmed && trimmed.length <= 120) onSave(trimmed);
      }}
    >
      <Input
        value={value}
        maxLength={120}
        onChange={(e) => setValue(e.target.value)}
        aria-label="Title"
        className="h-8 min-w-0 flex-[1_1_180px]"
        autoFocus
        data-testid="artifact-rename-input"
      />
      <Button type="submit" size="sm" disabled={!trimmed || pending}>
        Save
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
        Cancel
      </Button>
    </form>
  );
}

function VersionList({
  artifact,
  shown,
  onView,
}: {
  artifact: ArtifactDetail;
  shown: number;
  onView: (n: number) => void;
}) {
  const actions = useArtifactActions(artifact.id);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const restore = async (v: ArtifactVersion) => {
    setMessage(null);
    try {
      const r = await actions.restore.mutateAsync({
        version: v.n,
        base: artifact.latest_version,
      });
      setMessage({
        ok: true,
        text: `Restored version ${v.n} as version ${r.version.n}.`,
      });
      onView(r.version.n);
    } catch (err) {
      setMessage({ ok: false, text: refusalWords(err) });
    }
  };
  return (
    <div data-testid="artifact-versions">
      <ol className="border-border divide-border max-h-72 divide-y overflow-auto rounded-lg border">
        {artifact.versions.map((v) => {
          const lineage = lineageWords(v.lineage, v.lineage_source);
          const note = safeField(v.note);
          return (
            <li
              key={v.n}
              className={cn(
                "flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2",
                v.n === shown && "bg-muted/50",
              )}
              data-version={v.n}
            >
              <span className="w-8 font-medium tabular-nums">v{v.n}</span>
              <div className="min-w-0 flex-[1_1_180px] text-xs">
                <p className="text-foreground">
                  {originWords(v.origin)}
                  <span className="text-muted-foreground">
                    {" · "}
                    {atText(v.created_at)}
                  </span>
                </p>
                {lineage && <p className="text-muted-foreground">{lineage}</p>}
                {note && (
                  <p className="text-muted-foreground truncate" title={note}>
                    The assistant&rsquo;s note: {note}
                  </p>
                )}
              </div>
              {v.n !== shown && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => onView(v.n)}
                  data-testid="artifact-version-view"
                  className="max-md:min-h-11"
                >
                  View
                </Button>
              )}
              {v.n !== artifact.latest_version && !artifact.archived && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={actions.restore.isPending}
                  onClick={() => void restore(v)}
                  data-testid="artifact-version-restore"
                  className="max-md:min-h-11"
                >
                  <RotateCcwIcon />
                  Restore this version
                </Button>
              )}
            </li>
          );
        })}
      </ol>
      <p className="text-muted-foreground mt-1 text-xs">
        Restore makes a new version with that version&rsquo;s content; nothing
        is deleted.
      </p>
      {message && (
        <p
          role={message.ok ? "status" : "alert"}
          className={cn(
            "mt-1 text-sm",
            message.ok ? "text-foreground" : "text-destructive",
          )}
        >
          {message.text}
        </p>
      )}
    </div>
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
  const matches = typed.trim() === title;
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
            <label className="text-sm" htmlFor="artifact-delete-confirm">
              Type the title to confirm
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
