"use client";

import { XIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ago } from "@/core/apps/wording";
import { hasChanges, lineDiff } from "@/core/artifacts/line-diff";
import {
  isCodeKind,
  type ArtifactDetail,
  type ArtifactKind,
  type ArtifactVersion,
  type ArtifactVersionDetail,
} from "@/core/artifacts/store-api";
import {
  useArtifactActions,
  useArtifactVersion,
} from "@/core/artifacts/store-hooks";
import { refusalWords, versionSummary } from "@/core/artifacts/store-logic";
import { cn } from "@/lib/utils";

import { codeOf } from "./artifact-content";
import { IconButton } from "./viewer-parts";

/** Kinds whose two versions can be compared as text. */
export function canCompare(kind: ArtifactKind) {
  return kind !== "svg" && kind !== "image" && kind !== "file";
}

/** A version's comparable text: its source (code kinds: every file). */
export function compareText(
  kind: ArtifactKind,
  d: ArtifactVersionDetail | undefined,
): string | null {
  if (!d) return null;
  if (kind === "code") return codeOf(d.content).text;
  if (kind === "chart") return JSON.stringify(d.content ?? null, null, 2);
  if (kind === "react") {
    const files = d.source?.files ?? {};
    return Object.keys(files)
      .sort()
      .map((f) => `=== ${f} ===\n${files[f] ?? ""}`)
      .join("\n");
  }
  if (kind === "webapp") {
    return (d.files ?? []).map((f) => `${f.path} (${f.size} bytes)`).join("\n");
  }
  return typeof d.content === "string" ? d.content : "";
}

/**
 * The versions drawer: each version with when and a plain-language summary
 * (its note, trimmed), View, Compare (with the version shown) and Restore
 * (which makes a NEW version; nothing is deleted). On the right at 260 px;
 * the host shows it as a bottom sheet at phone width.
 */
export function VersionsDrawer({
  artifact,
  shown,
  onView,
  onClose,
  asSheet,
}: {
  artifact: ArtifactDetail;
  shown: number;
  onView: (n: number) => void;
  onClose: () => void;
  asSheet: boolean;
}) {
  const actions = useArtifactActions(artifact.id);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const [compare, setCompare] = useState<number | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);

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
  const newestFirst = [...artifact.versions].sort((a, b) => b.n - a.n);
  const comparable = canCompare(artifact.kind);
  return (
    <aside
      aria-label="Versions"
      className={cn(
        "bg-card flex min-h-0 flex-col gap-3 overflow-y-auto p-4",
        asSheet
          ? "max-h-[70vh] w-full"
          : "border-border w-[260px] shrink-0 border-l",
      )}
      onKeyDown={(e) => {
        if (e.key === "Escape" && !asSheet) {
          e.preventDefault();
          e.stopPropagation();
          onClose();
        }
      }}
      data-testid="artifact-versions"
    >
      <div className="flex items-center justify-between">
        <h3
          ref={heading}
          tabIndex={-1}
          className="text-sm font-semibold outline-none"
        >
          Versions
        </h3>
        {!asSheet && (
          <IconButton
            label="Close versions"
            onClick={onClose}
            data-testid="artifact-versions-close"
          >
            <XIcon />
          </IconButton>
        )}
      </div>
      <ol className="flex flex-col gap-2">
        {newestFirst.map((v) => {
          const current = v.n === shown;
          return (
            <li
              key={v.n}
              data-version={v.n}
              className={cn(
                "rounded-[10px] border px-3 py-2.5",
                current ? "border-primary" : "border-border",
              )}
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-medium">
                  v{v.n}
                  {v.n === artifact.latest_version ? " · latest" : ""}
                  {current ? " · shown" : ""}
                </span>
                <span className="text-muted-foreground shrink-0 text-xs">
                  {ago(v.created_at)}
                </span>
              </div>
              <p
                className="text-muted-foreground line-clamp-2 text-[13px]"
                data-testid="artifact-version-summary"
              >
                {versionSummary(v)}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[13px]">
                {!current && (
                  <button
                    type="button"
                    className="text-primary hover:underline pointer-coarse:min-h-11"
                    onClick={() => onView(v.n)}
                    data-testid="artifact-version-view"
                  >
                    View
                  </button>
                )}
                {!current && comparable && (
                  <button
                    type="button"
                    className="text-primary hover:underline pointer-coarse:min-h-11"
                    onClick={() => setCompare(v.n)}
                    data-testid="artifact-version-compare"
                  >
                    Compare
                  </button>
                )}
                {v.n !== artifact.latest_version && !artifact.archived && (
                  <button
                    type="button"
                    className="text-primary hover:underline disabled:opacity-50 pointer-coarse:min-h-11"
                    disabled={actions.restore.isPending}
                    onClick={() => void restore(v)}
                    data-testid="artifact-version-restore"
                  >
                    Restore
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      <p className="text-muted-foreground text-xs">
        Restore makes a new version with that version&rsquo;s content; nothing
        is deleted.
      </p>
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
      {compare !== null && (
        <CompareDialog
          artifact={artifact}
          older={Math.min(compare, shown)}
          newer={Math.max(compare, shown)}
          onClose={() => setCompare(null)}
        />
      )}
    </aside>
  );
}

/** Two versions' sources, as a line diff (unchanged runs collapsed). */
function CompareDialog({
  artifact,
  older,
  newer,
  onClose,
}: {
  artifact: ArtifactDetail;
  older: number;
  newer: number;
  onClose: () => void;
}) {
  const a = useArtifactVersion(artifact.id, older);
  const b = useArtifactVersion(artifact.id, newer);
  const before = compareText(artifact.kind, a.data);
  const after = compareText(artifact.kind, b.data);
  const rows = useMemo(
    () =>
      before === null || after === null ? undefined : lineDiff(before, after),
    [before, after],
  );
  const failed = a.isError || b.isError;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="max-h-[85vh] max-w-[min(860px,calc(100vw-32px))] overflow-hidden sm:max-w-[min(860px,calc(100vw-32px))]"
        data-testid="artifact-compare"
      >
        <DialogHeader>
          <DialogTitle>
            Compare v{older} with v{newer}
          </DialogTitle>
          <DialogDescription>
            Lines removed in v{newer} are marked &minus;, lines added +.
          </DialogDescription>
        </DialogHeader>
        {isCodeKind(artifact.kind) && (
          <h4 className="text-sm font-semibold">Code changes</h4>
        )}
        {failed ? (
          <p role="status" className="text-muted-foreground text-sm">
            Couldn&rsquo;t load these versions.
          </p>
        ) : rows === undefined ? (
          <p role="status" className="text-muted-foreground text-sm">
            Loading…
          </p>
        ) : rows === null ? (
          <p role="status" className="text-muted-foreground text-sm">
            These versions are too large to compare here.
          </p>
        ) : !hasChanges(rows) ? (
          <p role="status" className="text-sm" data-testid="artifact-diff-same">
            No changes between these versions.
          </p>
        ) : (
          <pre
            className="border-border bg-background max-h-[60vh] min-w-0 overflow-auto rounded-md border p-2 font-mono text-xs leading-5"
            data-testid="artifact-diff"
          >
            {rows.map((r, i) =>
              r.type === "skip" ? (
                <div
                  key={i}
                  className="text-muted-foreground italic"
                  data-row="skip"
                >
                  {`… ${r.count} unchanged ${r.count === 1 ? "line" : "lines"}`}
                </div>
              ) : (
                <div
                  key={i}
                  data-row={r.type}
                  className={cn(
                    "whitespace-pre-wrap",
                    r.type === "add" && "bg-success/15",
                    r.type === "del" && "bg-destructive/15",
                  )}
                >
                  {r.type === "add" ? "+ " : r.type === "del" ? "− " : "  "}
                  {r.text}
                </div>
              ),
            )}
          </pre>
        )}
      </DialogContent>
    </Dialog>
  );
}
