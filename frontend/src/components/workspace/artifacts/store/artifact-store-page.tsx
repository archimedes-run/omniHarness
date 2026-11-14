"use client";

import {
  MessageSquareIcon,
  PackageIcon,
  PinIcon,
  SearchIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PageColumn, PageHeader } from "@/components/workspace/page-kit";
import { ago } from "@/core/apps/wording";
import {
  ArtifactsApiError,
  type ArtifactKind,
  type ArtifactSummary,
  type ListQuery,
} from "@/core/artifacts/store-api";
import {
  useArtifactList,
  useArtifactUsage,
} from "@/core/artifacts/store-hooks";
import {
  formatBytes,
  isImported,
  KIND_WORDS,
  livesInChat,
  titleText,
} from "@/core/artifacts/store-logic";
import { cn } from "@/lib/utils";

import { ArtifactContent, KindIcon } from "./artifact-content";

type View = "all" | "recent" | "pinned" | "archived" | "chat";
const VIEWS: { id: View; label: string }[] = [
  { id: "all", label: "All" },
  { id: "recent", label: "Recent" },
  { id: "pinned", label: "Pinned" },
  { id: "chat", label: "By chat" },
  { id: "archived", label: "Archived" },
];
const KINDS: ArtifactKind[] = [
  "markdown",
  "code",
  "chart",
  "mermaid",
  "svg",
  "image",
  "file",
];

/**
 * Spec 012 FR-034: the Artifact store. Search (title and text), kind chips,
 * All, Recent, Pinned, By chat and Archived; a grid of cards with small
 * previews; each opens /workspace/artifacts/[id]. Titles are data, shown as
 * text. A server without the routes answers 404 once and the page says so
 * quietly (no retries).
 */
export function ArtifactStorePage() {
  const [view, setView] = useState<View>("all");
  const [kind, setKind] = useState<ArtifactKind | null>(null);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => {
    document.title = "Artifacts";
  }, []);

  const query: ListQuery = useMemo(
    () => ({
      ...(kind ? { kind } : {}),
      ...(q ? { q } : {}),
      ...(view === "pinned" ? { pinned: true } : {}),
      ...(view === "archived" ? { archived: true } : {}),
    }),
    [kind, q, view],
  );
  const { data, error, isLoading } = useArtifactList(query);
  const missing =
    error instanceof ArtifactsApiError &&
    (error.status === 404 || error.code === "artifacts_unavailable");
  const usage = useArtifactUsage(!!data);

  const items = useMemo(() => {
    const list = [...(data?.artifacts ?? [])];
    if (view === "recent") {
      list.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    }
    return list;
  }, [data, view]);

  return (
    <PageColumn>
      <PageHeader
        title="Artifacts"
        description="Everything the assistant made for you, across your chats: documents, code, charts, diagrams and images."
        actions={
          usage.data || data?.usage ? (
            <UsageMeter usage={(usage.data ?? data?.usage)!} />
          ) : null
        }
      />
      <div className="flex flex-col gap-3">
        <div className="relative">
          <SearchIcon
            className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
            aria-hidden
          />
          <Input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search titles and text"
            aria-label="Search artifacts"
            className="pl-9 max-md:h-11"
            data-testid="artifact-search"
          />
        </div>
        <ChipRow label="View">
          {VIEWS.map((v) => (
            <Chip
              key={v.id}
              active={view === v.id}
              onClick={() => setView(v.id)}
              testId={`artifact-view-${v.id}`}
            >
              {v.label}
            </Chip>
          ))}
        </ChipRow>
        <ChipRow label="Kind">
          <Chip
            active={kind === null}
            onClick={() => setKind(null)}
            testId="artifact-kind-all"
          >
            All kinds
          </Chip>
          {KINDS.map((k) => (
            <Chip
              key={k}
              active={kind === k}
              onClick={() => setKind(kind === k ? null : k)}
              testId={`artifact-kind-${k}`}
            >
              <KindIcon kind={k} className="size-3.5" />
              {KIND_WORDS[k]}
            </Chip>
          ))}
        </ChipRow>
      </div>
      {isLoading ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : missing ? (
        <EmptyState
          title="Artifacts aren't available here yet"
          body="This server doesn't have the artifact store. Nothing is lost: files from your chats stay in their chats."
          testId="artifacts-unavailable"
        />
      ) : error ? (
        <p className="text-destructive" role="alert">
          Couldn&rsquo;t load your artifacts. Try again in a moment.
        </p>
      ) : items.length === 0 ? (
        q || kind || view !== "all" ? (
          <EmptyState
            title="Nothing matches"
            body="Try another search, kind or view."
            testId="artifacts-none-match"
          />
        ) : (
          <EmptyState
            title="No artifacts yet"
            body="Ask for one in any chat, for example “draft a one-page project brief” or “chart last week’s CI pass rate”."
            testId="artifacts-empty"
          />
        )
      ) : view === "chat" ? (
        <ByChat items={items} />
      ) : (
        <Grid items={items} />
      )}
    </PageColumn>
  );
}

function UsageMeter({ usage }: { usage: { used: number; cap: number } }) {
  const share =
    usage.cap > 0 ? Math.min(1, Math.max(0, usage.used / usage.cap)) : 0;
  const words = `${formatBytes(usage.used)} of ${formatBytes(usage.cap)} used`;
  return (
    <div className="flex w-48 flex-col gap-1" data-testid="artifact-usage">
      <span className="text-muted-foreground text-xs">{words}</span>
      <div
        role="meter"
        aria-label="Artifact storage used"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(share * 100)}
        aria-valuetext={words}
        className="bg-muted h-1.5 overflow-hidden rounded-full"
      >
        <div
          className={cn(
            "h-full rounded-full",
            share > 0.9 ? "bg-destructive" : "bg-primary",
          )}
          style={{ width: `${Math.max(share * 100, share > 0 ? 2 : 0)}%` }}
        />
      </div>
    </div>
  );
}

function ChipRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {children}
    </div>
  );
}

function Chip({
  active,
  onClick,
  testId,
  children,
}: {
  active: boolean;
  onClick: () => void;
  testId: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      data-testid={testId}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs transition-colors max-md:h-11",
        active
          ? "bg-foreground text-background border-foreground"
          : "border-border text-foreground hover:bg-muted",
      )}
    >
      {children}
    </button>
  );
}

function EmptyState({
  title,
  body,
  testId,
}: {
  title: string;
  body: string;
  testId: string;
}) {
  return (
    <div
      className="bg-card border-border flex flex-col items-start gap-2 rounded-xl border px-[18px] py-6"
      data-testid={testId}
    >
      <PackageIcon className="text-muted-foreground size-5" aria-hidden />
      <p className="font-medium">{title}</p>
      <p className="text-muted-foreground">{body}</p>
    </div>
  );
}

function Grid({ items }: { items: ArtifactSummary[] }) {
  return (
    <ul
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
      data-testid="artifact-grid"
    >
      {items.map((a) => (
        <StoreCard key={a.id} artifact={a} />
      ))}
    </ul>
  );
}

function ByChat({ items }: { items: ArtifactSummary[] }) {
  const groups = new Map<string, ArtifactSummary[]>();
  for (const a of items) {
    const key = a.origin_thread_id ?? "";
    const list = groups.get(key) ?? [];
    list.push(a);
    groups.set(key, list);
  }
  return (
    <div className="flex flex-col gap-6" data-testid="artifact-by-chat">
      {[...groups.entries()].map(([thread, list]) => (
        <section key={thread || "none"} className="flex flex-col gap-2">
          <h2 className="flex flex-wrap items-baseline gap-2 text-[15px] font-semibold">
            {thread ? (
              <>
                <span>Chat from {ago(list[list.length - 1]!.created_at)}</span>
                <Link
                  href={`/workspace/chats/${encodeURIComponent(thread)}`}
                  className="text-primary text-xs font-normal underline"
                >
                  Open the chat
                </Link>
              </>
            ) : (
              <span>Not from a chat</span>
            )}
          </h2>
          <Grid items={list} />
        </section>
      ))}
    </div>
  );
}

function StoreCard({ artifact }: { artifact: ArtifactSummary }) {
  const title = titleText(artifact.title);
  const href = `/workspace/artifacts/${encodeURIComponent(artifact.id)}`;
  const inChat = livesInChat(artifact);
  return (
    <li
      className="bg-card border-border flex min-w-0 flex-col overflow-hidden rounded-xl border"
      data-testid="artifact-store-card"
      data-artifact={artifact.id}
      data-kind={artifact.kind}
    >
      <div className="bg-muted/30 border-border h-36 min-w-0 overflow-hidden border-b p-3">
        {inChat ? (
          <p className="text-muted-foreground text-xs">
            Too large for the store: it lives in its chat.
          </p>
        ) : artifact.kind === "file" ? (
          <div className="text-muted-foreground flex h-full items-center justify-center">
            <KindIcon kind="file" className="size-8" />
          </div>
        ) : (
          <ArtifactContent
            artifact={artifact}
            version={artifact.latest_version}
            compact
            drawDiagrams={false}
          />
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-1 px-3 py-2.5">
        <div className="flex min-w-0 items-center gap-1.5">
          <KindIcon kind={artifact.kind} className="text-muted-foreground" />
          {inChat && artifact.origin_thread_id ? (
            <Link
              href={`/workspace/chats/${encodeURIComponent(artifact.origin_thread_id)}`}
              className="min-w-0 flex-1 truncate font-semibold hover:underline"
              title={title}
              data-testid="artifact-store-card-link"
            >
              {title}
            </Link>
          ) : (
            <Link
              href={href}
              className="min-w-0 flex-1 truncate font-semibold hover:underline"
              title={title}
              data-testid="artifact-store-card-link"
            >
              {title}
            </Link>
          )}
          {artifact.pinned && (
            <PinIcon
              className="text-muted-foreground size-3.5 shrink-0"
              aria-label="Pinned"
            />
          )}
        </div>
        <p className="text-muted-foreground flex flex-wrap gap-x-2 text-xs">
          <span>{KIND_WORDS[artifact.kind]}</span>
          <span>v{artifact.latest_version}</span>
          <span>{ago(artifact.updated_at)}</span>
          {isImported(artifact.lineage, artifact.lineage_source) ? (
            <span>Imported from its chat</span>
          ) : (
            artifact.lineage === "content" && <span>From content read</span>
          )}
        </p>
        {artifact.origin_thread_id && (
          <Link
            href={`/workspace/chats/${encodeURIComponent(artifact.origin_thread_id)}`}
            className="text-primary inline-flex w-fit items-center gap-1 text-xs underline"
            data-testid="artifact-store-open-chat"
          >
            <MessageSquareIcon className="size-3" aria-hidden />
            Open the chat that made it
          </Link>
        )}
      </div>
    </li>
  );
}
