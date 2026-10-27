import { readdirSync, readFileSync, statSync } from "fs";
import { join, relative } from "path";

import { describe, expect, it } from "vitest";

/**
 * Every frontend surface that shows agent- or content-derived text uses THE
 * display sanitiser (src/core/display/safe.ts), the mirror of the backend's
 * (backend/tests/gates/test_display_render_paths.py lists the backend side).
 *
 * RENDER_PATHS: the files that render such text, or the one place a list of
 * it is read for every card. NOTED: files that touch such fields but receive
 * them already made safe in a RENDER_PATHS file, each with why.
 */
const SRC = join(__dirname, "..", "..", "src");

const RENDER_PATHS: Record<string, string> = {
  "core/confirmations/api.ts":
    "every confirmation/suggestion card (chat, Home's Waiting on you) reads plan, targets and origin from loadPending",
  "components/workspace/ledger/ledger-write-step.tsx":
    "chat: the ledger step's disclosed write",
  "components/workspace/runs/run-summary.tsx":
    "the run summary page: targets and source labels",
  "components/workspace/home/moved-card.tsx": "Home: what moved today",
  "core/notification/hooks.ts": "notifications: a chat's title and reply",
  "components/workspace/confirmations/pending-action-card.tsx":
    "a confirmed card's result line (the tool's result, whose links stay real for the model); its other fields come from loadPending, made safe",
  "components/workspace/code-jobs/code-job-card.tsx":
    "chat: a coding job's title, commands, file paths, outputs and the worker's words",
  "core/tools/search-results.ts":
    "chat: a search step's results (title, site, snippet; search-result-list.tsx renders them)",
};

const NOTED: Record<string, string> = {
  "components/workspace/home/approval-row.tsx":
    "renders fields loadPending (core/confirmations/api.ts) made safe",
  "core/confirmations/types.ts": "type declarations only",
  "core/confirmations/logic.ts":
    "chooses the origin sentence from fields loadPending made safe",
  "core/studio/run-summary.ts": "fetches; run-summary.tsx renders",
  "core/ledger/api.ts": "parses; ledger-write-step.tsx renders",
};

/** Fields that carry agent- or content-derived text to the screen. */
const CONTENT_FIELD =
  /\.(plan_text|source_label|origin_label|arguments_display)\b|parseLedgerResult\(/;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory()
      ? files(path)
      : /\.(ts|tsx)$/.test(name)
        ? [path]
        : [];
  });
}

/** Components that put an item's own link on screen: each must pass it
 *  through providerLink, so only a provably provider-own link is live. */
const LINK_PATHS: Record<string, string> = {
  "components/workspace/home/moved-card.tsx": "Home: an outside item's link",
};

describe("content-derived text is shown only through core/display/safe", () => {
  it.each(Object.keys(LINK_PATHS))("%s proves its links", (file) => {
    const source = readFileSync(join(SRC, file), "utf-8");
    expect(source, `${file}: ${LINK_PATHS[file]}`).toMatch(/\bproviderLink\(/);
    expect(source).not.toMatch(/href=\{item\.url\}/);
  });

  it.each(Object.keys(RENDER_PATHS))("%s calls the sanitiser", (file) => {
    const source = readFileSync(join(SRC, file), "utf-8");
    expect(source, `${file}: ${RENDER_PATHS[file]}`).toMatch(
      /from "(@\/core\/display\/safe|\.\.?\/(\.\.\/)*display\/safe)"/,
    );
    expect(source).toMatch(/\bsafe(Field|Lines)\(/);
  });

  it("every file touching a content field is listed", () => {
    const unlisted = files(SRC)
      .map((path) => relative(SRC, path))
      .filter((file) => !file.startsWith("core/display/"))
      .filter((file) =>
        CONTENT_FIELD.test(readFileSync(join(SRC, file), "utf-8")),
      )
      .filter((file) => !(file in RENDER_PATHS) && !(file in NOTED));
    expect(unlisted).toEqual([]);
  });
});
