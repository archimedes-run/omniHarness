"use client";

import {
  DownloadIcon,
  HammerIcon,
  MessageSquarePlusIcon,
  PencilIcon,
} from "lucide-react";
import { useRef, useState } from "react";

import { useOptionalPromptInputController } from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  ArtifactsApiError,
  type ArtifactDetail,
  downloadUrl,
  type ReactSource,
} from "@/core/artifacts/store-api";
import {
  useArtifactVersion,
  useCodeActions,
} from "@/core/artifacts/store-hooks";
import { refusalWords, titleText } from "@/core/artifacts/store-logic";
import { safeField } from "@/core/display/safe";
import { cn } from "@/lib/utils";

import { ArtifactCode } from "./artifact-code";
import {
  CheckDetails,
  CheckLabel,
  FullscreenButton,
  LockedFrame,
} from "./artifact-frame";

const LANG: Record<string, string> = {
  tsx: "tsx",
  ts: "typescript",
  jsx: "jsx",
  js: "javascript",
  css: "css",
  json: "json",
};

/**
 * Spec 012 Slice 2: an html or react version in the panel and on the full
 * page: its checks label, Preview (the locked frame, full screen) and Code
 * (read-only CodeMirror; react: one file at a time; Edit source + Rebuild).
 * Opening the panel is "Open anyway": a version that failed its checks is
 * shown, labelled.
 */
export function CodeKindView({
  artifact,
  version,
  onVersionChange,
}: {
  artifact: ArtifactDetail;
  version: number;
  onVersionChange: (n: number) => void;
}) {
  const [tab, setTab] = useState<"preview" | "code">("preview");
  const [editing, setEditing] = useState(false);
  const [page, setPage] = useState<string | undefined>(undefined);
  const v = artifact.versions.find((x) => x.n === version);
  const code = v?.code;
  const { data: detail } = useArtifactVersion(artifact.id, version);
  const actions = useCodeActions(artifact.id);
  const box = useRef<HTMLDivElement | null>(null);
  const title = titleText(artifact.title);
  const build = artifact.code?.build;
  const pages = (detail?.webapp?.files ?? [])
    .map((f) => f.path)
    .filter((p) => /\.html?$/i.test(p));
  const canRebuild =
    artifact.kind === "react" &&
    !artifact.archived &&
    version === artifact.latest_version &&
    build?.state !== "running";

  return (
    <div
      className="flex min-h-0 min-w-0 flex-1 flex-col gap-2"
      data-testid="artifact-code-kind"
    >
      {code?.build_state === "ok" && (
        <>
          <CheckLabel
            check={code.check}
            pending={actions.checkAgain.isPending}
            onCheckAgain={() => actions.checkAgain.mutate(version)}
          />
          <CheckDetails check={code.check} findings={code.findings} />
        </>
      )}
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
      <div
        className="flex flex-wrap items-center gap-1.5"
        role="tablist"
        aria-label="View"
      >
        {(["preview", "code"] as const).map((t) => (
          <Button
            key={t}
            type="button"
            size="sm"
            role="tab"
            aria-selected={tab === t}
            variant={tab === t ? "secondary" : "ghost"}
            onClick={() => setTab(t)}
            data-testid={`artifact-tab-${t}`}
            className="max-md:min-h-11"
          >
            {t === "preview" ? "Preview" : "Code"}
          </Button>
        ))}
        <span className="flex-1" />
        {tab === "preview" && code?.build_state === "ok" && (
          <FullscreenButton target={box} />
        )}
        {tab === "code" && canRebuild && !editing && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setEditing(true)}
            data-testid="artifact-edit-source"
            className="max-md:min-h-11"
          >
            <PencilIcon />
            Edit source
          </Button>
        )}
        <AskButton artifactId={artifact.id} version={version} />
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {code?.build_state === "ok" && (
          <Button asChild size="sm" variant="ghost" className="max-md:min-h-11">
            <a
              href={downloadUrl(artifact.id, version, "page")}
              download
              data-testid="artifact-download-page"
            >
              <DownloadIcon />
              Page (.html)
            </a>
          </Button>
        )}
        <Button asChild size="sm" variant="ghost" className="max-md:min-h-11">
          <a
            href={downloadUrl(artifact.id, version, "source")}
            download
            data-testid="artifact-download-source"
          >
            <DownloadIcon />
            Source (.zip)
          </a>
        </Button>
      </div>
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
            ref={box}
            className="bg-background flex min-h-[60vh] min-w-0 flex-1 flex-col [&:fullscreen]:p-0"
          >
            {artifact.kind === "webapp" && pages.length > 1 && (
              <div
                className="flex flex-wrap gap-1 pb-2"
                data-testid="artifact-webapp-pages"
              >
                {pages.map((p) => (
                  <Button
                    key={p}
                    type="button"
                    size="sm"
                    variant={
                      (page ?? detail?.webapp?.entry) === p
                        ? "secondary"
                        : "ghost"
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
        )
      ) : editing && detail?.source ? (
        <ReactSourceEditor
          artifact={artifact}
          source={detail.source}
          onDone={() => setEditing(false)}
        />
      ) : artifact.kind === "webapp" ? (
        <ul className="text-sm" data-testid="artifact-webapp-files">
          {(detail?.webapp?.files ?? []).map((f) => (
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

/** FR-011: "Ask the assistant to change this" puts a reference (id and
 * version, never the content) into this chat's composer. Only in a chat. */
export function AskButton({
  artifactId,
  version,
}: {
  artifactId: string;
  version: number;
}) {
  const controller = useOptionalPromptInputController();
  if (!controller) return null;
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      onClick={() => {
        const ref = `[artifact ${artifactId} v${version}] `;
        const now = controller.textInput.value;
        controller.textInput.setInput(now.includes(ref) ? now : `${ref}${now}`);
        requestAnimationFrame(() =>
          document
            .querySelector<HTMLTextAreaElement>("textarea[name='message']")
            ?.focus(),
        );
      }}
      data-testid="artifact-ask-change"
      className="max-md:min-h-11"
    >
      <MessageSquarePlusIcon />
      Ask the assistant to change this
    </Button>
  );
}
