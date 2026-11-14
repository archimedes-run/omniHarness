import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SaveDownload } from "@/components/workspace/artifacts/store/artifact-save";
import { downloadUrl } from "@/core/artifacts/store-api";
import { downloadForms, fileView } from "@/core/artifacts/store-logic";

/**
 * Spec 012, the owner's correction: Save and Download on every artifact,
 * download forms per kind, how a file artifact is shown, and the controls
 * staying hidden on a gateway without the save routes.
 */

const ID = "Qm3x9V2kPz8aLr0tYw4bNc";

function render(saved: boolean | undefined, kind = "markdown") {
  const client = new QueryClient();
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client },
      createElement(SaveDownload, {
        artifact: { id: ID, kind: kind as never, saved, archived: false },
        version: 2,
      }),
    ),
  );
}

describe("Save and Download", () => {
  it("unsaved: Save and a Download link to the download route", () => {
    const html = render(false);
    expect(html).toContain('data-testid="artifact-save"');
    expect(html).toContain(`href="/api/artifacts/${ID}/versions/2/download"`);
  });

  it("saved: Saved (with a menu), never Save", () => {
    const html = render(true);
    expect(html).toContain('data-testid="artifact-saved"');
    expect(html).not.toContain('data-testid="artifact-save"');
  });

  it("no `saved` field (the gateway has no save routes): nothing at all", () => {
    expect(render(undefined)).toBe("");
  });

  it("react offers two forms in a menu; others one link", () => {
    expect(downloadForms("react").map((f) => f.label)).toEqual([
      "Built page (.html)",
      "Source (.zip)",
    ]);
    expect(downloadForms("markdown")).toHaveLength(1);
    expect(render(false, "react")).toContain(
      'data-testid="artifact-download-menu"',
    );
    expect(downloadUrl(ID, 3, "source")).toBe(
      `/api/artifacts/${ID}/versions/3/download?form=source`,
    );
  });
});

describe("a file artifact is shown by its media type", () => {
  it.each([
    ["text/csv", "text"],
    ["text/html; charset=utf-8", "text"],
    ["application/json", "text"],
    ["image/png", "image"],
    ["image/svg+xml", "download"],
    ["application/zip", "download"],
    ["application/octet-stream", "download"],
    [null, "download"],
  ])("%s → %s", (type, view) => {
    expect(fileView(type)).toBe(view);
  });
});
