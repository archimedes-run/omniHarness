"use client";

import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { ArtifactPanel } from "@/components/workspace/artifacts/store/artifact-panel";
import { PageColumn } from "@/components/workspace/page-kit";

/** Spec 012: one artifact, full page (the side panel's viewer). */
function ArtifactPage() {
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const raw = Number(search.get("v"));
  const version = Number.isInteger(raw) && raw > 0 ? raw : null;
  const artifactId = decodeURIComponent(id);
  return (
    <PageColumn>
      <Link
        href="/workspace/artifacts"
        className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1 text-sm max-md:min-h-11"
      >
        <ArrowLeftIcon className="size-4" aria-hidden />
        Artifacts
      </Link>
      <ArtifactPanel
        id={artifactId}
        version={version}
        mode="page"
        onVersionChange={(n) =>
          router.replace(
            `/workspace/artifacts/${encodeURIComponent(artifactId)}?v=${n}`,
          )
        }
      />
    </PageColumn>
  );
}

export default function Page() {
  return (
    <Suspense fallback={null}>
      <ArtifactPage />
    </Suspense>
  );
}
