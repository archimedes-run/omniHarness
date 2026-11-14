"use client";

import {
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
import { useEffect, useMemo, useState } from "react";
import { defaultRehypePlugins } from "streamdown";

import { Markdown } from "@/components/ai-elements/markdown";
import { parseChartSpec } from "@/core/artifacts/chart-spec";
import { drawMermaid, offscreenContainer } from "@/core/artifacts/mermaid";
import type {
  ArtifactKind,
  ArtifactSummary,
  ArtifactVersionDetail,
  CodeContent,
} from "@/core/artifacts/store-api";
import { contentUrl } from "@/core/artifacts/store-api";
import { useArtifactVersion } from "@/core/artifacts/store-hooks";
import { previewLines, titleText } from "@/core/artifacts/store-logic";
import { checkSvgText, svgDataUrl } from "@/core/artifacts/svg-allowlist";
import { streamdownPlugins } from "@/core/streamdown";
import { cn } from "@/lib/utils";

import { ArtifactChart } from "./artifact-chart";

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
      <Markdown
        remarkPlugins={streamdownPlugins.remarkPlugins}
        rehypePlugins={NO_RAW_HTML}
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
  const [state, setState] = useState<
    { s: "drawing" } | { s: "ok"; url: string } | { s: "failed" }
  >({ s: "drawing" });
  useEffect(() => {
    let live = true;
    setState({ s: "drawing" });
    void drawMermaid(source, dark, {
      load: async () => (await import("mermaid")).default,
      check: checkSvgText,
      toUrl: svgDataUrl,
      container: offscreenContainer,
    }).then((r) => {
      if (!live) return;
      setState(r.ok ? { s: "ok", url: r.url } : { s: "failed" });
    });
    return () => {
      live = false;
    };
  }, [source, dark]);

  if (state.s === "drawing") {
    return (
      <p className="text-muted-foreground text-sm" role="status">
        Drawing the diagram…
      </p>
    );
  }
  if (state.s === "failed") {
    return (
      <div className="flex min-w-0 flex-col gap-2" data-testid="mermaid-failed">
        <p className="text-muted-foreground text-sm" role="status">
          Couldn&rsquo;t draw this diagram. Here is its source.
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
    <img
      src={state.url}
      alt={title}
      data-testid="artifact-mermaid"
      className={cn(
        "mx-auto block h-auto max-w-full",
        compact ? "max-h-40" : "max-h-[70vh]",
      )}
    />
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
  >;
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
  const { data, error, isLoading } = useArtifactVersion(artifact.id, version);
  const title = titleText(artifact.title);

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
    <a
      href={contentUrl(artifact.id, version)}
      className="text-primary text-sm underline"
      download
    >
      Download this file
    </a>
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
  return compact ? <PlainPreview text={text} /> : <MarkdownView text={text} />;
}
