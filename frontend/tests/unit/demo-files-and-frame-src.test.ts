import fs from "fs";
import os from "os";
import path from "path";

import { describe, expect, it } from "vitest";

import { GET } from "@/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route";
import {
  demoHeaders,
  demoThreadDir,
  resolveDemoFile,
} from "@/core/demo/demo-files";
import { workspaceHostPolicy } from "@/core/security/app-host-csp";

/** Spec 012 S2 review: the demo file route stays inside its thread's folder,
 * says what it serves, and the page frames /mock/api/threads/ only in demo
 * mode. */

function tree() {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "demo-"));
  const dir = path.join(
    cwd,
    "public",
    "demo",
    "threads",
    "t1",
    "user-data",
    "outputs",
  );
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "page.html"), "<p>demo</p>");
  fs.writeFileSync(path.join(cwd, "secret.txt"), "SECRET");
  fs.mkdirSync(path.join(cwd, "public", "demo", "threads", "t2"), {
    recursive: true,
  });
  fs.writeFileSync(
    path.join(cwd, "public", "demo", "threads", "t2", "thread.json"),
    "{}",
  );
  fs.symlinkSync(path.join(cwd, "secret.txt"), path.join(dir, "link.txt"));
  return cwd;
}

describe("demo files", () => {
  it("stays inside the thread's folder whatever either segment holds", () => {
    const cwd = tree();
    expect(resolveDemoFile(cwd, "t1", "user-data/outputs/page.html")).toMatch(
      /page\.html$/,
    );
    for (const bad of [
      "../../../secret.txt",
      "user-data/../../t2/thread.json",
      "/etc/passwd",
      "user-data/outputs/link.txt",
      "a\0b",
    ]) {
      expect(resolveDemoFile(cwd, "t1", bad), bad).toBeNull();
    }
    for (const id of ["..", "../..", "t1/../t2", "t1%2F..", ""]) {
      expect(demoThreadDir(cwd, id), id).toBeNull();
      expect(resolveDemoFile(cwd, id, "thread.json"), id).toBeNull();
    }
  });

  it("answers with an explicit type, nosniff and a sandbox", () => {
    expect(demoHeaders("x/page.html")).toEqual({
      "Content-Type": "text/html; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "sandbox",
    });
    expect(demoHeaders("x/blob.weird")["Content-Type"]).toBe(
      "application/octet-stream",
    );
  });

  it("the route refuses a traversal in either segment and serves a real file with the headers", async () => {
    const call = (thread_id: string, artifact_path: string[]) =>
      GET({ nextUrl: new URL("http://x/") } as never, {
        params: Promise.resolve({ thread_id, artifact_path }),
      });
    const threads = fs.readdirSync(
      path.join(process.cwd(), "public", "demo", "threads"),
    );
    const t = threads[0]!;
    const file = fs.readdirSync(
      path.join(
        process.cwd(),
        "public",
        "demo",
        "threads",
        t,
        "user-data",
        "outputs",
      ),
    )[0]!;
    const ok = await call(t, ["mnt", "user-data", "outputs", file]);
    expect(ok.status).toBe(200);
    expect(ok.headers.get("x-content-type-options")).toBe("nosniff");
    expect(ok.headers.get("content-security-policy")).toBe("sandbox");
    expect(ok.headers.get("content-type")).toBeTruthy();
    expect((await call("..", ["mnt", "..", "..", "package.json"])).status).toBe(
      404,
    );
    expect(
      (await call(t, ["mnt", "..", "..", "..", "..", "package.json"])).status,
    ).toBe(404);
    expect((await call(`${t}/../..`, ["mnt", "package.json"])).status).toBe(
      404,
    );
  });
});

describe("page frame-src", () => {
  it("lists /mock/api/threads/ only in demo mode", () => {
    const frameSrc = (csp: string) =>
      /frame-src ([^;]+)/.exec(csp)![1]!.split(" ");
    const normal = frameSrc(workspaceHostPolicy("app.example:2026"));
    const demo = frameSrc(
      workspaceHostPolicy("app.example:2026", { demo: true }),
    );
    expect(normal).toEqual([
      "http://app.example:2026/api/artifacts/",
      "http://app.example:2026/api/threads/",
      "http://app.example:2026/mermaid-frame/",
    ]);
    expect(demo).toEqual([
      ...normal,
      "http://app.example:2026/mock/api/threads/",
    ]);
    expect(normal.join(" ")).not.toMatch(/blob:|'self'/);
  });
});
