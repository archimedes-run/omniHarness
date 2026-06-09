import { getBackendBaseURL } from "../config";
import type { AgentThread } from "../threads";

import type { ArtifactManifest } from "./api";

const ARTIFACT_MANIFEST_PREFIX = "artifact-manifest:";

export function urlOfArtifact({
  filepath,
  threadId,
  download = false,
  isMock = false,
}: {
  filepath: string;
  threadId: string;
  download?: boolean;
  isMock?: boolean;
}) {
  if (isMock) {
    return `${getBackendBaseURL()}/mock/api/threads/${threadId}/artifacts${filepath}${download ? "?download=true" : ""}`;
  }
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${filepath}${download ? "?download=true" : ""}`;
}

export function urlOfArtifactPreview({
  filepath,
  threadId,
  isMock = false,
}: {
  filepath: string;
  threadId: string;
  isMock?: boolean;
}) {
  if (isMock) {
    return `${getBackendBaseURL()}/mock/api/threads/${threadId}/artifacts/preview${filepath}`;
  }
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts/preview${filepath}`;
}

export function extractArtifactsFromThread(thread: AgentThread) {
  return thread.values.artifacts ?? [];
}

export function resolveArtifactURL(absolutePath: string, threadId: string) {
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${absolutePath}`;
}

export function artifactManifestValue(manifest: ArtifactManifest) {
  return `${ARTIFACT_MANIFEST_PREFIX}${encodeURIComponent(manifest.id)}`;
}

export function parseArtifactManifestValue(value: string): string | null {
  if (!value.startsWith(ARTIFACT_MANIFEST_PREFIX)) {
    return null;
  }
  return decodeURIComponent(value.slice(ARTIFACT_MANIFEST_PREFIX.length));
}

export function isArtifactManifestValue(value: string) {
  return parseArtifactManifestValue(value) !== null;
}

export function normalizeArtifactEntries(entries: string[]) {
  const seen = new Set<string>();
  const normalized: string[] = [];

  for (const entry of entries) {
    const trimmed = entry.trim();
    if (!trimmed || seen.has(trimmed)) {
      continue;
    }
    seen.add(trimmed);
    normalized.push(trimmed);
  }

  return normalized;
}

export function normalizeArtifactPath(path: string) {
  return path.replace(/\/+/g, "/").replace(/\/$/, "");
}

export function suppressManifestDuplicateFiles(
  files: string[],
  manifests: ArtifactManifest[],
) {
  const manifestPaths = new Set(
    manifests.flatMap((manifest) =>
      [manifest.entrypoint_path, manifest.manifest_path]
        .filter(
          (path): path is string => typeof path === "string" && path.length > 0,
        )
        .map(normalizeArtifactPath),
    ),
  );

  return files.filter(
    (file) => !manifestPaths.has(normalizeArtifactPath(file)),
  );
}

export function artifactDisplayName(
  value: string,
  manifests: ArtifactManifest[],
  fallbackName: (path: string) => string,
) {
  const manifestId = parseArtifactManifestValue(value);
  if (!manifestId) {
    return fallbackName(value);
  }
  return (
    manifests.find((manifest) => manifest.id === manifestId)?.title ??
    manifestId
  );
}
