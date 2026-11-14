"use client";

import { PanelRightOpenIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ArtifactKind } from "@/core/artifacts/store-api";
import { useStoreArtifact } from "@/core/artifacts/store-hooks";
import {
  KIND_WORDS,
  lineageWords,
  panelKey,
  titleText,
} from "@/core/artifacts/store-logic";

import { useArtifacts } from "../context";

import { ArtifactContent, KindIcon } from "./artifact-content";

/**
 * Spec 012 FR-009: the artifact card at the turn that made it, bound to the
 * version that turn made. An update shows "Version N" of the same artifact;
 * an older card says "Latest: vM" and still opens its own version.
 */
export function ArtifactCard({
  artifactId,
  version,
  kind,
}: {
  artifactId: string;
  version: number;
  kind: ArtifactKind;
}) {
  const { data, error, isLoading } = useStoreArtifact(artifactId);
  const { select, setOpen } = useArtifacts();
  const open = () => {
    select(panelKey(artifactId, version));
    setOpen(true);
  };
  const v = data?.versions.find((x) => x.n === version);
  const lineage = v ? lineageWords(v.lineage, v.lineage_source) : null;
  const title = data ? titleText(data.title) : KIND_WORDS[kind];

  return (
    <article
      className="bg-card border-border flex w-full max-w-xl min-w-0 flex-col gap-2 rounded-xl border px-4 py-3"
      data-testid="artifact-card"
      data-artifact={artifactId}
      data-version={version}
    >
      <div className="flex min-w-0 items-center gap-2">
        <KindIcon kind={data?.kind ?? kind} className="text-muted-foreground" />
        <h3
          className="min-w-0 flex-1 truncate text-sm font-semibold"
          title={title}
        >
          {title}
        </h3>
        <span
          className="text-muted-foreground shrink-0 text-xs"
          data-testid="artifact-card-version"
        >
          {version === 1 ? "v1" : `Version ${version}`}
        </span>
      </div>
      {data && data.latest_version > version && (
        <p
          className="text-muted-foreground text-xs"
          data-testid="artifact-card-latest"
        >
          Latest: v{data.latest_version}. This card shows version {version}.
        </p>
      )}
      {data?.archived && <p className="text-warning text-xs">Archived</p>}
      {lineage && (
        <p
          className="border-warning/40 text-foreground w-fit rounded-md border px-2 py-0.5 text-xs"
          data-testid="artifact-card-lineage"
        >
          {lineage}
        </p>
      )}
      <div className="max-h-44 min-w-0 overflow-hidden">
        {isLoading ? (
          <p className="text-muted-foreground text-xs" role="status">
            Loading…
          </p>
        ) : error || !data ? (
          <p className="text-muted-foreground text-xs" role="status">
            This artifact isn&rsquo;t available.
          </p>
        ) : (
          <ArtifactContent artifact={data} version={version} compact />
        )}
      </div>
      {data && (
        <div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={open}
            data-testid="artifact-card-open"
            className="max-md:min-h-11"
          >
            <PanelRightOpenIcon />
            Open
          </Button>
        </div>
      )}
    </article>
  );
}
