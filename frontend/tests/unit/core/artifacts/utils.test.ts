import { expect, test } from "vitest";

import { urlOfArtifact, urlOfArtifactPreview } from "@/core/artifacts/utils";

test("builds artifact preview URLs under the preview route", () => {
  expect(
    urlOfArtifactPreview({
      filepath: "/mnt/user-data/outputs/site/index.html",
      threadId: "thread-1",
    }),
  ).toBe(
    "/api/threads/thread-1/artifacts/preview/mnt/user-data/outputs/site/index.html",
  );
});

test("keeps artifact download URLs on the existing artifacts route", () => {
  expect(
    urlOfArtifact({
      filepath: "/mnt/user-data/outputs/site/index.html",
      threadId: "thread-1",
      download: true,
    }),
  ).toBe(
    "/api/threads/thread-1/artifacts/mnt/user-data/outputs/site/index.html?download=true",
  );
});
