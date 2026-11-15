import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SaveDownload } from "@/components/workspace/artifacts/store/artifact-save";
import { downloadUrl, type ArtifactSummary } from "@/core/artifacts/store-api";
import {
  downloadForms,
  originChatOf,
  storeViewQuery,
  webAppDirOf,
} from "@/core/artifacts/store-logic";

/**
 * Spec 012, the owner's save model (api.md "Saved and unsaved"): Save and
 * Download on every artifact through the gateway's download route, the
 * download forms per kind, the store's tabs always sending `saved`, a
 * deleted chat's artifact, and "Save to artifacts" on a coding job's site
 * saving its directory.
 */

const ID = "Qm3x9V2kPz8aLr0tYw4bNc";

function render(
  saved: boolean,
  kind = "markdown",
  extra: Partial<ArtifactSummary> & { download?: boolean } = {},
) {
  const client = new QueryClient();
  const { download, ...rest } = extra;
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client },
      createElement(SaveDownload, {
        artifact: {
          id: ID,
          kind: kind as never,
          saved,
          latest_version: 2,
          ...rest,
        },
        version: 2,
        download,
      }),
    ),
  );
}

describe("Save and Download", () => {
  it("unsaved: Save and a Download link to the download route", () => {
    const html = render(false);
    expect(html).toContain('data-testid="artifact-store-save"');
    expect(html).toContain(`href="/api/artifacts/${ID}/versions/2/download"`);
  });

  it("saved: Saved (with a menu), never Save", () => {
    const html = render(true);
    expect(html).toContain('data-testid="artifact-store-saved"');
    expect(html).not.toContain('data-testid="artifact-store-save"');
  });

  it("an archived artifact can still be saved", () => {
    const html = render(false, "markdown", { archived: true });
    expect(html).toMatch(/<button[^>]*data-testid="artifact-store-save"/);
    expect(html).not.toMatch(
      /<button[^>]* disabled=""[^>]*data-testid="artifact-store-save"/,
    );
  });

  it("download={false} (the code-kind viewer has its own): Save only", () => {
    const html = render(false, "html", { download: false });
    expect(html).toContain('data-testid="artifact-store-save"');
    expect(html).not.toContain("/download");
  });

  it("html and react: page and source in a menu; source is ?source=zip", () => {
    for (const kind of ["html", "react"] as const) {
      expect(downloadForms(kind)).toEqual([
        { form: "page", label: "Page (.html)" },
        { form: "source", label: "Source (.zip)" },
      ]);
      expect(render(false, kind)).toContain(
        'data-testid="artifact-store-download-menu"',
      );
    }
    expect(downloadUrl(ID, 3, "source")).toBe(
      `/api/artifacts/${ID}/versions/3/download?source=zip`,
    );
    expect(downloadUrl(ID, 3, "page")).toBe(
      `/api/artifacts/${ID}/versions/3/download`,
    );
  });

  it("a version that did not build offers its source only", () => {
    expect(downloadForms("react", false)).toEqual([
      { form: "source", label: "Source (.zip)" },
    ]);
    const html = render(false, "react", {
      code: {
        build_state: "build_failed",
        check_state: null,
        shown_version: 1,
        build: null,
      },
    });
    expect(html).toContain(
      `href="/api/artifacts/${ID}/versions/2/download?source=zip"`,
    );
    expect(html).not.toContain('versions/2/download"');
  });

  it("webapp: one .zip of its files; static kinds: one file", () => {
    expect(downloadForms("webapp")).toEqual([
      { form: "page", label: "Files (.zip)" },
    ]);
    for (const k of [
      "markdown",
      "code",
      "svg",
      "mermaid",
      "chart",
      "image",
      "file",
    ] as const) {
      expect(downloadForms(k)).toEqual([{ form: "page", label: "Download" }]);
    }
    const html = render(false, "webapp");
    expect(html).toContain('data-testid="artifact-store-download"');
    expect(html).toContain(`href="/api/artifacts/${ID}/versions/2/download"`);
  });
});

describe("the store's tabs always send `saved` (the API default is all)", () => {
  it.each([
    ["saved", { saved: true }],
    ["recent", { saved: true }],
    ["unsaved", { saved: false }],
    ["all", { saved: "all" }],
    ["pinned", { saved: "all", pinned: true }],
    ["archived", { saved: "all", archived: true }],
  ] as const)("%s", (view, query) => {
    expect(storeViewQuery(view)).toEqual(query);
  });
});

describe("a deleted chat's artifact", () => {
  it("is labelled, with no link to the chat", () => {
    expect(
      originChatOf({ origin_thread_id: "t-1", origin_deleted: true }),
    ).toEqual({ deleted: true });
    expect(
      originChatOf({ origin_thread_id: "t-1", origin_deleted: false }),
    ).toEqual({ threadId: "t-1" });
    expect(
      originChatOf({ origin_thread_id: null, origin_deleted: false }),
    ).toBeNull();
  });
});

describe("Save to artifacts on a coding job's site saves its directory", () => {
  it.each([
    ["/mnt/user-data/outputs/site/index.html", "/mnt/user-data/outputs/site"],
    ["/mnt/user-data/outputs/report.md", "/mnt/user-data/outputs/report.md"],
    [
      "/mnt/user-data/outputs/site/about/index.htm",
      "/mnt/user-data/outputs/site/about/index.htm",
    ],
  ])("%s → %s", (path, dir) => {
    expect(webAppDirOf(path)).toBe(dir);
  });
});
