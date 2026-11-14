"use client";

import {
  AppWindowIcon,
  Globe2Icon,
  BarChart3Icon,
  Code2Icon,
  FileIcon,
  FileTextIcon,
  ImageIcon,
  type LucideIcon,
  NetworkIcon,
  ShapesIcon,
} from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useEffect, useMemo, useRef, useState } from "react";
import { defaultRehypePlugins } from "streamdown";

import { Markdown } from "@/components/ai-elements/markdown";
import { parseChartSpec } from "@/core/artifacts/chart-spec";
import { drawMermaid, UNSUPPORTED_REASON } from "@/core/artifacts/mermaid";
import { renderInFrame } from "@/core/artifacts/mermaid-frame-host";
import type {
  ArtifactKind,
  ArtifactSummary,
  ArtifactVersionDetail,
  CodeContent,
} from "@/core/artifacts/store-api";
import {
  CODE_KINDS,
  contentUrl,
  downloadUrl,
  shotUrl,
} from "@/core/artifacts/store-api";
import { useArtifactVersion } from "@/core/artifacts/store-hooks";
import {
  fileView,
  previewLines,
  previewMarkdown,
  titleText,
} from "@/core/artifacts/store-logic";
import { checkSvgText, svgDataUrl } from "@/core/artifacts/svg-allowlist";
import { streamdownPlugins } from "@/core/streamdown";
import { cn } from "@/lib/utils";

import { ArtifactChart } from "./artifact-chart";
import { LockedFrame } from "./locked-frame";

/**
 * Spec 012 FR-013: static kinds rendered by the host with NO raw-HTML sink.
 * markdown: the app's renderer with raw HTML off (the content URL guard is
 * its last step); code: CodeMirror, read only; svg and image: ONLY
 * `<img src>` of the content route; mermaid: drawn to an image
 * (core/artifacts/mermaid.ts); chart: React SVG from the data spec.
 */

export const KIND_ICONS: Record<ArtifactKind, LucideIcon> = {
  markdown: FileTextIcon,
  code: Code2Icon,
  svg: ShapesIcon,
  mermaid: NetworkIcon,
  chart: BarChart3Icon,
  image: ImageIcon,
  file: FileIcon,
  html: Globe2Icon,
  react: AppWindowIcon,
  webapp: AppWindowIcon,
};

export function KindIcon({
  kind,
  className,
}: {
  kind: ArtifactKind;
  className?: string;
}) {
  const Icon = KIND_ICONS[kind] ?? FileIcon;
  return <Icon className={cn("size-4 shrink-0", className)} aria-hidden />;
}

// Raw HTML OFF: streamdown's sanitize and harden steps, without rehype-raw.
const NO_RAW_HTML = [
  defaultRehypePlugins.sanitize!,
  defaultRehypePlugins.harden!,
].filter(Boolean);

export function MarkdownView({ text }: { text: string }) {
  return (
    <div data-testid="artifact-markdown" className="min-w-0 text-sm">
      {/* A stored document is complete: no "repair" of markers that look
          unclosed (it appended stray `**`/`__*` at the end). */}
      <Markdown
        remarkPlugins={streamdownPlugins.remarkPlugins}
        rehypePlugins={NO_RAW_HTML}
        parseIncompleteMarkdown={false}
      >
        {text}
      </Markdown>
    </div>
  );
}

const CodeView = dynamic(
  () => import("./artifact-code").then((m) => m.ArtifactCode),
  {
    ssr: false,
    loading: () => (
      <div className="text-muted-foreground p-4 text-sm">Loading code…</div>
    ),
  },
);
export { CodeView };

export function codeOf(content: unknown): CodeContent {
  if (content && typeof content === "object" && !Array.isArray(content)) {
    const c = content as Record<string, unknown>;
    return {
      language: typeof c.language === "string" ? c.language : "text",
      text: typeof c.text === "string" ? c.text : "",
    };
  }
  return { language: "text", text: typeof content === "string" ? content : "" };
}

export function ImageView({
  src,
  alt,
  compact,
}: {
  src: string;
  alt: string;
  compact?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <p className="text-muted-foreground text-sm" role="status">
        Couldn&rsquo;t load this image.
      </p>
    );
  }
  return (
    <img
      src={src}
      alt={alt}
      referrerPolicy="no-referrer"
      decoding="async"
      loading="lazy"
      onError={() => setFailed(true)}
      data-testid="artifact-image"
      className={cn(
        "bg-muted/40 mx-auto block h-auto max-w-full rounded-md object-contain",
        compact ? "max-h-40" : "max-h-[70vh]",
      )}
    />
  );
}

/** True once the element has been on screen (cards draw only then). */
function useSeen(enabled: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  const [seen, setSeen] = useState(!enabled);
  useEffect(() => {
    if (!enabled || seen) return;
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true);
          io.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [enabled, seen]);
  return [ref, seen] as const;
}

export function MermaidView({
  source,
  title,
  compact,
}: {
  source: string;
  title: string;
  compact?: boolean;
}) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  // A card in the chat draws only once it is on screen.
  const [ref, seen] = useSeen(!!compact);
  const [state, setState] = useState<
    | { s: "drawing" }
    | { s: "ok"; url: string; linksRemoved: boolean }
    | { s: "failed"; unsupported: boolean }
  >({ s: "drawing" });
  useEffect(() => {
    if (!seen) return;
    let live = true;
    setState({ s: "drawing" });
    void drawMermaid(source, dark, {
      render: renderInFrame,
      check: checkSvgText,
      toUrl: svgDataUrl,
    }).then((r) => {
      if (!live) return;
      setState(
        r.ok
          ? { s: "ok", url: r.url, linksRemoved: r.linksRemoved }
          : { s: "failed", unsupported: r.reason === UNSUPPORTED_REASON },
      );
    });
    return () => {
      live = false;
    };
  }, [source, dark, seen]);

  if (state.s === "drawing") {
    return (
      <div ref={ref}>
        <p className="text-muted-foreground text-sm" role="status">
          {seen ? "Drawing the diagram…" : "Diagram"}
        </p>
      </div>
    );
  }
  if (state.s === "failed") {
    return (
      <div className="flex min-w-0 flex-col gap-2" data-testid="mermaid-failed">
        <p className="text-muted-foreground text-sm" role="status">
          {state.unsupported
            ? "Journey diagrams aren’t supported yet. Here is its source."
            : "Couldn’t draw this diagram. Here is its source."}
        </p>
        {compact ? (
          <PlainPreview text={source} />
        ) : (
          <CodeView text={source} language="mermaid" />
        )}
      </div>
    );
  }
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <img
        src={state.url}
        alt={title}
        data-testid="artifact-mermaid"
        className={cn(
          "mx-auto block h-auto max-w-full",
          compact ? "max-h-40" : "max-h-[70vh]",
        )}
      />
      {state.linksRemoved && !compact && (
        <p
          className="text-muted-foreground text-xs"
          data-testid="mermaid-links-removed"
        >
          Links in diagrams are not supported; they were left out.
        </p>
      )}
    </div>
  );
}

/** A few lines of text as text (cards, store grid). */
export function PlainPreview({
  text,
  mono,
  lines = 6,
}: {
  text: string;
  mono?: boolean;
  lines?: number;
}) {
  return (
    <pre
      className={cn(
        "text-muted-foreground max-h-32 overflow-hidden text-xs leading-5 break-words whitespace-pre-wrap",
        mono ? "font-mono" : "font-sans",
      )}
      data-testid="artifact-plain-preview"
    >
      {previewLines(text, lines)}
    </pre>
  );
}

/** One version's content, rendered for its kind. */
export function ArtifactContent({
  artifact,
  version,
  compact = false,
  drawDiagrams = true,
}: {
  artifact: Pick<
    ArtifactSummary,
    "id" | "kind" | "title" | "imported_from" | "origin_thread_id"
  > &
    Partial<Pick<ArtifactSummary, "media_type">>;
  version: number;
  compact?: boolean;
  /** False in the store grid: a diagram shows its source lines there. */
  drawDiagrams?: boolean;
}) {
  const needsBody =
    artifact.kind === "markdown" ||
    artifact.kind === "code" ||
    artifact.kind === "mermaid" ||
    artifact.kind === "chart";
  const code = isCodeKind(artifact.kind);
  const { data, error, isLoading } = useArtifactVersion(
    code ? null : artifact.id,
    version,
  );
  const title = titleText(artifact.title);

  // Programs: only ever in the locked frame; a preview is the checks'
  // screenshot (or an icon), never a live frame per card.
  if (code) {
    return compact ? (
      <CodeShot
        artifactId={artifact.id}
        version={version}
        kind={artifact.kind}
      />
    ) : (
      <LockedFrame artifactId={artifact.id} version={version} title={title} />
    );
  }
  if (isLoading) {
    return (
      <p className="text-muted-foreground text-sm" role="status">
        Loading…
      </p>
    );
  }
  if (error || !data) {
    return (
      <p className="text-muted-foreground text-sm" role="status">
        Couldn&rsquo;t load this version.
      </p>
    );
  }
  if (data.stored === "chat") {
    return <LivesInChat threadId={artifact.origin_thread_id} />;
  }
  if (needsBody) {
    return (
      <TextKind
        kind={artifact.kind}
        detail={data}
        title={title}
        compact={compact}
        drawDiagrams={drawDiagrams}
      />
    );
  }
  if (artifact.kind === "svg" || artifact.kind === "image") {
    return (
      <ImageView
        src={contentUrl(artifact.id, version)}
        alt={title}
        compact={compact}
      />
    );
  }
  return (
    <FileView
      artifactId={artifact.id}
      version={version}
      mediaType={artifact.media_type ?? data.media_type}
      title={title}
      compact={compact}
    />
  );
}

function isCodeKind(kind: ArtifactKind): boolean {
  return (CODE_KINDS as readonly string[]).includes(kind);
}

/** A code artifact's preview: the checks' screenshot, else its icon. */
function CodeShot({
  artifactId,
  version,
  kind,
}: {
  artifactId: string;
  version: number;
  kind: ArtifactKind;
}) {
  const { resolvedTheme } = useTheme();
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div
        className="text-muted-foreground flex h-24 flex-col items-center justify-center gap-1 text-xs"
        data-testid="artifact-code-icon"
      >
        <KindIcon kind={kind} className="size-8" />
        Open to view
      </div>
    );
  }
  return (
    <img
      src={shotUrl(
        artifactId,
        version,
        resolvedTheme === "dark" ? "dark" : "light",
      )}
      alt=""
      referrerPolicy="no-referrer"
      loading="lazy"
      onError={() => setFailed(true)}
      data-testid="artifact-code-shot"
      className="mx-auto block h-auto max-h-32 max-w-full rounded-md object-contain"
    />
  );
}

const TEXT_CAP = 2 * 1024 * 1024;

/** A `file` artifact: text as text, images as images, else a card to
 * download it. Nothing is ever rendered as a page. */
function FileView({
  artifactId,
  version,
  mediaType,
  title,
  compact,
}: {
  artifactId: string;
  version: number;
  mediaType: string;
  title: string;
  compact: boolean;
}) {
  const view = fileView(mediaType);
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (view !== "text") return;
    let live = true;
    void fetch(contentUrl(artifactId, version), { credentials: "include" })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        const body = await r.text();
        if (live) setText(body.slice(0, TEXT_CAP));
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [artifactId, version, view]);
  if (view === "image") {
    return (
      <ImageView
        src={contentUrl(artifactId, version)}
        alt={title}
        compact={compact}
      />
    );
  }
  if (view === "text" && !failed) {
    if (text === null) {
      return (
        <p className="text-muted-foreground text-sm" role="status">
          Loading…
        </p>
      );
    }
    return compact ? (
      <PlainPreview text={text} mono />
    ) : (
      <CodeView text={text} language="text" />
    );
  }
  return (
    <div
      className="flex flex-col items-start gap-2"
      data-testid="artifact-download-to-view"
    >
      <KindIcon kind="file" className="text-muted-foreground size-6" />
      <p className="text-muted-foreground text-sm">
        This file can&rsquo;t be shown here.
      </p>
      {!compact && (
        <a
          href={downloadUrl(artifactId, version)}
          className="text-primary text-sm underline"
          download
        >
          Download to view
        </a>
      )}
    </div>
  );
}

export function LivesInChat({ threadId }: { threadId: string | null }) {
  return (
    <p className="text-muted-foreground text-sm" data-testid="lives-in-chat">
      This file is too large for the store and lives in its chat.{" "}
      {threadId && (
        <Link
          href={`/workspace/chats/${encodeURIComponent(threadId)}`}
          className="text-primary underline"
        >
          Open the chat
        </Link>
      )}
    </p>
  );
}

function TextKind({
  kind,
  detail,
  title,
  compact,
  drawDiagrams,
}: {
  kind: ArtifactKind;
  detail: ArtifactVersionDetail;
  title: string;
  compact: boolean;
  drawDiagrams: boolean;
}) {
  const chart = useMemo(
    () => (kind === "chart" ? parseChartSpec(detail.content) : null),
    [kind, detail.content],
  );
  if (kind === "chart") {
    if (!chart?.ok) {
      return (
        <p className="text-muted-foreground text-sm" role="status">
          Couldn&rsquo;t draw this chart.
        </p>
      );
    }
    return <ArtifactChart spec={chart.spec} compact={compact} />;
  }
  if (kind === "code") {
    const code = codeOf(detail.content);
    return compact ? (
      <PlainPreview text={code.text} mono />
    ) : (
      <CodeView text={code.text} language={code.language} />
    );
  }
  const text = typeof detail.content === "string" ? detail.content : "";
  if (kind === "mermaid" && !drawDiagrams) {
    return <PlainPreview text={text} mono />;
  }
  if (kind === "mermaid") {
    return <MermaidView source={text} title={title} compact={compact} />;
  }
  return compact ? (
    <div
      className="pointer-events-none max-h-32 overflow-hidden text-xs [&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm"
      data-testid="artifact-markdown-preview"
    >
      <MarkdownView text={previewMarkdown(text, 6, 400)} />
    </div>
  ) : (
    <MarkdownView text={text} />
  );
}
