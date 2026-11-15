"use client";

import { HammerIcon } from "lucide-react";
import dynamic from "next/dynamic";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  ArtifactsApiError,
  type ArtifactDetail,
  type ReactSource,
} from "@/core/artifacts/store-api";
import {
  useArtifactVersion,
  useCodeActions,
} from "@/core/artifacts/store-hooks";
import { refusalWords, titleText } from "@/core/artifacts/store-logic";
import { safeField } from "@/core/display/safe";
import { cn } from "@/lib/utils";

// CodeMirror loads only when the Code tab is opened (an empty chat ships none).
const ArtifactCode = dynamic(
  () => import("./artifact-code").then((m) => m.ArtifactCode),
  { ssr: false },
);
import { LockedFrame } from "./artifact-frame";
import { DEVICE_WIDTH, type Device } from "./viewer-parts";

const LANG: Record<string, string> = {
  tsx: "tsx",
  ts: "typescript",
  jsx: "jsx",
  js: "javascript",
  css: "css",
  json: "json",
};

/**
 * Spec 012 Slice 2: an html, react or webapp version in the viewer: Preview
 * (the locked frame, at the chosen preview size) or Code (read-only
 * CodeMirror; react: one file at a time; the source editor + Rebuild).
 * The viewer's header owns the tab, the size, the downloads, the checks
 * chip and full screen (whose target is `boxRef`). Opening the panel is
 * "Open anyway": a version that failed its checks is shown, labelled.
 */
export function CodeKindView({
  artifact,
  version,
  onVersionChange,
  tab,
  device = "desk",
  editingSource = false,
  onEditSourceDone,
  boxRef,
}: {
  artifact: ArtifactDetail;
  version: number;
  onVersionChange: (n: number) => void;
  tab: "preview" | "code";
  device?: Device;
  editingSource?: boolean;
  onEditSourceDone?: () => void;
  boxRef?: React.RefObject<HTMLDivElement | null>;
}) {
  const [page, setPage] = useState<string | undefined>(undefined);
  const v = artifact.versions.find((x) => x.n === version);
  const code = v?.code;
  const { data: detail } = useArtifactVersion(artifact.id, version);
  const title = titleText(artifact.title);
  const build = artifact.code?.build;
  const pages = (detail?.pages ?? []).filter((p) => p.ok).map((p) => p.path);

  return (
    <div
      className="flex min-h-0 min-w-0 flex-1 flex-col gap-2"
      data-testid="artifact-code-kind"
    >
      {build?.state === "running" && (
        <p
          className="text-muted-foreground text-xs"
          role="status"
          data-testid="artifact-build-running"
        >
          Building in this chat&rsquo;s sandbox…
        </p>
      )}
      {build &&
        (build.state === "interrupted" ||
          (build.state === "failed" && build.result_version === null)) && (
          <p className="text-warning text-xs" role="status">
            The last rebuild{" "}
            {build.state === "interrupted"
              ? "stopped before it finished"
              : `failed${build.reason ? `: ${safeField(build.reason)}` : ""}`}
            .
          </p>
        )}
      {tab === "preview" ? (
        code?.build_state === "build_failed" ? (
          <div
            className="flex flex-col gap-2 text-sm"
            data-testid="artifact-build-failed"
          >
            <p>
              This version did not build.
              {artifact.code?.shown_version ? (
                <>
                  {" "}
                  <button
                    type="button"
                    className="text-primary underline"
                    onClick={() =>
                      onVersionChange(artifact.code!.shown_version!)
                    }
                  >
                    Show version {artifact.code.shown_version}
                  </button>
                  , the last one that built.
                </>
              ) : null}
            </p>
            {detail?.build_log && (
              <pre
                className="bg-muted max-h-64 overflow-auto rounded-md p-2 text-xs whitespace-pre-wrap"
                data-testid="artifact-build-log"
              >
                {detail.build_log}
              </pre>
            )}
          </div>
        ) : (
          <div
            ref={boxRef}
            className="[&:fullscreen]:bg-background flex min-w-0 flex-1 flex-col items-center [&:fullscreen]:p-0 [&:fullscreen>[data-device]]:flex-1"
            data-testid="artifact-preview-box"
          >
            <div
              className="border-border bg-card flex w-full max-w-full flex-col overflow-hidden rounded-[14px] border"
              style={{
                width: DEVICE_WIDTH[device],
                marginInline: "auto",
              }}
              data-testid="artifact-device-frame"
              data-device={device}
            >
              {artifact.kind === "webapp" && pages.length > 1 && (
                <div
                  className="border-border flex flex-wrap gap-1 border-b p-2"
                  data-testid="artifact-webapp-pages"
                >
                  {pages.map((p) => (
                    <Button
                      key={p}
                      type="button"
                      size="sm"
                      variant={
                        (page ?? detail?.entry) === p ? "secondary" : "ghost"
                      }
                      onClick={() => setPage(p)}
                      className="h-7 font-mono text-xs max-md:min-h-11"
                    >
                      {safeField(p)}
                    </Button>
                  ))}
                </div>
              )}
              <LockedFrame
                entry={artifact.kind === "webapp" ? page : undefined}
                artifactId={artifact.id}
                version={version}
                title={title}
                variant="panel"
                className="flex min-h-0 flex-1 flex-col"
              />
            </div>
          </div>
        )
      ) : editingSource && detail?.source ? (
        <ReactSourceEditor
          artifact={artifact}
          source={detail.source}
          onDone={() => onEditSourceDone?.()}
        />
      ) : artifact.kind === "webapp" ? (
        <ul className="text-sm" data-testid="artifact-webapp-files">
          {(detail?.files ?? []).map((f) => (
            <li key={f.path} className="font-mono text-xs">
              {safeField(f.path)}{" "}
              <span className="text-muted-foreground">({f.size} bytes)</span>
            </li>
          ))}
        </ul>
      ) : artifact.kind === "react" ? (
        <ReactFiles source={detail?.source ?? null} />
      ) : (
        <ArtifactCode
          text={typeof detail?.content === "string" ? detail.content : ""}
          language="html"
        />
      )}
    </div>
  );
}

/** True when a react version's source can be edited and rebuilt here. */
export function canRebuild(artifact: ArtifactDetail, version: number) {
  return (
    artifact.kind === "react" &&
    !artifact.archived &&
    version === artifact.latest_version &&
    artifact.code?.build?.state !== "running"
  );
}

function ReactFiles({ source }: { source: ReactSource | null }) {
  const files = Object.keys(source?.files ?? {});
  const [file, setFile] = useState<string | null>(null);
  if (!source) return <p className="text-muted-foreground text-sm">Loading…</p>;
  const current =
    file && source.files[file] !== undefined ? file : source.entry;
  return (
    <div
      className="flex min-w-0 flex-col gap-2"
      data-testid="artifact-react-files"
    >
      <div className="flex flex-wrap gap-1">
        {files.map((f) => (
          <Button
            key={f}
            type="button"
            size="sm"
            variant={f === current ? "secondary" : "ghost"}
            onClick={() => setFile(f)}
            className="h-7 font-mono text-xs max-md:min-h-11"
          >
            {safeField(f)}
          </Button>
        ))}
      </div>
      <ArtifactCode
        text={source.files[current] ?? ""}
        language={LANG[current.split(".").pop() ?? ""] ?? "text"}
      />
    </div>
  );
}

function ReactSourceEditor({
  artifact,
  source,
  onDone,
}: {
  artifact: ArtifactDetail;
  source: ReactSource;
  onDone: () => void;
}) {
  const actions = useCodeActions(artifact.id);
  const [files, setFiles] = useState<Record<string, string>>(source.files);
  const [file, setFile] = useState(source.entry);
  const [error, setError] = useState<string | null>(null);
  const dirty = Object.keys(files).some((k) => files[k] !== source.files[k]);
  const rebuild = async () => {
    setError(null);
    try {
      await actions.rebuild.mutateAsync({
        base_version: artifact.latest_version,
        content: { entry: source.entry, files },
      });
      onDone();
    } catch (err) {
      setError(
        err instanceof ArtifactsApiError && err.code === "stale_base_version"
          ? "A newer version exists. Close the editor to see it."
          : refusalWords(err),
      );
    }
  };
  return (
    <div className="flex flex-col gap-2" data-testid="artifact-source-editor">
      <p className="text-muted-foreground text-xs">
        Editing version {artifact.latest_version}. Rebuild makes a new version
        from these files in this chat&rsquo;s sandbox.
      </p>
      <div className="flex flex-wrap gap-1">
        {Object.keys(files).map((f) => (
          <Button
            key={f}
            type="button"
            size="sm"
            variant={f === file ? "secondary" : "ghost"}
            onClick={() => setFile(f)}
            className={cn("h-7 font-mono text-xs max-md:min-h-11")}
          >
            {safeField(f)}
          </Button>
        ))}
      </div>
      <Textarea
        value={files[file] ?? ""}
        onChange={(e) => setFiles({ ...files, [file]: e.target.value })}
        spellCheck={false}
        className="min-h-64 font-mono text-sm"
        data-testid="artifact-source-draft"
        aria-label={`Source of ${file}`}
      />
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          disabled={!dirty || actions.rebuild.isPending}
          onClick={() => void rebuild()}
          data-testid="artifact-rebuild"
        >
          <HammerIcon />
          Rebuild
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          {dirty ? "Discard changes" : "Cancel"}
        </Button>
      </div>
    </div>
  );
}
