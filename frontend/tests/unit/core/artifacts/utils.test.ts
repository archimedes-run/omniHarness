import { expect, test } from "vitest";

import type { ArtifactManifest } from "@/core/artifacts/api";
import {
  artifactManifestValue,
  normalizeArtifactEntries,
  parseArtifactManifestValue,
  suppressManifestDuplicateFiles,
} from "@/core/artifacts/utils";

function manifest(overrides: Partial<ArtifactManifest> = {}): ArtifactManifest {
  return {
    id: "omniharness-next-site",
    title: "OmniHarness Next.js Marketing Site",
    type: "static_site",
    entrypoint: "index.html",
    root: ".",
    source_path: "/mnt/user-data/workspace/omniharness-next-site",
    preview: { mode: "static" },
    created_by: "agent",
    manifest_path:
      "/mnt/user-data/outputs/omniharness-next-site/artifact_manifest.json",
    root_path: "/mnt/user-data/outputs/omniharness-next-site",
    entrypoint_path: "/mnt/user-data/outputs/omniharness-next-site/index.html",
    ...overrides,
  };
}

test("artifactManifestValue round trips manifest ids", () => {
  const value = artifactManifestValue(manifest({ id: "site with spaces" }));

  expect(parseArtifactManifestValue(value)).toBe("site with spaces");
});

test("suppressManifestDuplicateFiles removes manifest entrypoint and manifest file", () => {
  const files = [
    "/mnt/user-data/outputs/omniharness-next-site/index.html",
    "/mnt/user-data/outputs/omniharness-next-site/artifact_manifest.json",
    "/mnt/user-data/outputs/report.md",
  ];

  expect(suppressManifestDuplicateFiles(files, [manifest()])).toEqual([
    "/mnt/user-data/outputs/report.md",
  ]);
});

test("suppressManifestDuplicateFiles keeps dynamic manifests without entrypoints stable", () => {
  const dynamicManifest = manifest({
    id: "dynamic-next-app",
    type: "web_app",
    entrypoint: null,
    entrypoint_path: null,
    manifest_path:
      "/mnt/user-data/outputs/dynamic-next-app/artifact_manifest.json",
    root_path: "/mnt/user-data/outputs/dynamic-next-app",
    preview: {
      mode: "dev_server",
      command: "npm run dev -- --hostname 0.0.0.0",
      port: 3000,
    },
  });

  const files = [
    "/mnt/user-data/outputs/dynamic-next-app/artifact_manifest.json",
    "/mnt/user-data/outputs/dynamic-next-app/README.md",
  ];

  expect(suppressManifestDuplicateFiles(files, [dynamicManifest])).toEqual([
    "/mnt/user-data/outputs/dynamic-next-app/README.md",
  ]);
});

test("normalizeArtifactEntries drops blank values and preserves first occurrence order", () => {
  expect(
    normalizeArtifactEntries([
      "",
      "  ",
      "/mnt/user-data/outputs/site/index.html",
      " /mnt/user-data/outputs/site/index.html ",
      "artifact-manifest:demo-app",
    ]),
  ).toEqual([
    "/mnt/user-data/outputs/site/index.html",
    "artifact-manifest:demo-app",
  ]);
});
