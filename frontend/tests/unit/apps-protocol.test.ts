import { describe, expect, it } from "vitest";

import {
  buildResult,
  checkFrameMessage,
  checkOpenUrl,
  isValidHostMessage,
  PROTOCOL_SCHEMA,
  RateLimiter,
} from "@/core/apps/protocol";
import { validateProtocolMessage } from "@/core/apps/validate";
import { ago, hashGroups, lastStateWords } from "@/core/apps/wording";

/**
 * Spec 011 FR-019, FR-022, FR-023: the protocol's validators, both ways. The
 * shim carries validate.js inline (tests/unit/apps-shim.test.ts proves the
 * text is the same), so these vectors are the shim's too.
 */

const approved = new Set(["calendar", "inbox"]);
const v = (
  direction: Parameters<typeof validateProtocolMessage>[1],
  m: unknown,
) => validateProtocolMessage(PROTOCOL_SCHEMA, direction, m);

describe("frame → host: only data, refresh, open, connect", () => {
  it("accepts each well-formed message", () => {
    for (const m of [
      { v: 1, type: "data", id: "r1", source: "calendar" },
      { v: 1, type: "refresh", id: "r2", source: "inbox" },
      { v: 1, type: "open", url: "https://github.com/a/b/pull/1" },
      { v: 1, type: "connect", source: "calendar" },
    ]) {
      expect(checkFrameMessage(m, approved)).toEqual({ ok: true, message: m });
    }
  });

  it("refuses unknown types, including host-only ones", () => {
    for (const type of [
      "init",
      "result",
      "update",
      "theme",
      "error",
      "write",
      "eval",
    ]) {
      const r = checkFrameMessage(
        { v: 1, type, id: "r1", source: "calendar" },
        approved,
      );
      expect(r.ok).toBe(false);
    }
    expect(checkFrameMessage({ v: 1, type: "init" }, approved)).toMatchObject({
      ok: false,
      reason: "unknown_type",
    });
  });

  it("refuses unknown keys, missing keys and bad values", () => {
    expect(
      checkFrameMessage(
        {
          v: 1,
          type: "refresh",
          id: "r1",
          source: "calendar",
          params: { q: "x" },
        },
        approved,
      ),
    ).toMatchObject({ ok: false, reason: "unknown_key:params" });
    expect(
      checkFrameMessage({ v: 1, type: "data", source: "calendar" }, approved),
    ).toMatchObject({
      ok: false,
      reason: "missing_key:id",
    });
    expect(
      checkFrameMessage(
        { v: 2, type: "data", id: "r1", source: "calendar" },
        approved,
      ),
    ).toMatchObject({ ok: false, reason: "bad_value:v" });
    expect(
      checkFrameMessage(
        { v: 1, type: "data", id: "r 1", source: "calendar" },
        approved,
      ),
    ).toMatchObject({ ok: false, reason: "bad_value:id" });
    expect(
      checkFrameMessage(
        { v: 1, type: "data", id: "r1", source: "Calendar" },
        approved,
      ),
    ).toMatchObject({ ok: false, reason: "bad_value:source" });
    expect(
      checkFrameMessage({ v: 1, type: "data", id: "r1", source: 7 }, approved),
    ).toMatchObject({ ok: false, reason: "bad_value:source" });
  });

  it("refuses a source outside the APPROVED manifest, and write-ish names", () => {
    for (const source of [
      "inbox_bodies",
      "gmail_delete_message",
      "other_app_calendar",
    ]) {
      expect(
        checkFrameMessage({ v: 1, type: "data", id: "r1", source }, approved),
      ).toEqual({
        ok: false,
        reason: "source_not_approved",
        type: "data",
        source,
      });
    }
    expect(
      checkFrameMessage({ v: 1, type: "connect", source: "github" }, approved),
    ).toMatchObject({ ok: false, reason: "source_not_approved" });
    // Nothing approved (the host has no grant): every source refused.
    expect(
      checkFrameMessage(
        { v: 1, type: "data", id: "r1", source: "calendar" },
        new Set(),
      ),
    ).toMatchObject({ ok: false, reason: "source_not_approved" });
  });

  it("refuses anything over 8 KB", () => {
    const url = "https://github.com/" + "a".repeat(2000);
    expect(checkFrameMessage({ v: 1, type: "open", url }, approved).ok).toBe(
      true,
    );
    const big = {
      v: 1,
      type: "open",
      url: "https://github.com/",
      pad: "x".repeat(9000),
    };
    expect(checkFrameMessage(big, approved)).toMatchObject({
      ok: false,
      reason: "too_large",
    });
    // Multi-byte characters count as bytes, not characters.
    const wide = {
      v: 1,
      type: "open",
      url: "https://github.com/" + "é".repeat(4100),
    };
    expect(checkFrameMessage(wide, approved)).toMatchObject({
      ok: false,
      reason: "too_large",
    });
  });

  it("refuses anything that is not a plain JSON object", () => {
    for (const raw of [
      null,
      "data",
      42,
      ["data"],
      new Date(),
      new Map([["type", "data"]]),
      { v: 1, type: "data", id: "r1", source: "calendar", when: new Date() },
      { v: 1, type: "data", id: "r1", source: "calendar", n: NaN },
      { v: 1, type: "data", id: "r1", source: "calendar", f: () => 1 },
      {
        v: 1,
        type: "data",
        id: "r1",
        source: "calendar",
        b: new Uint8Array(4),
      },
    ]) {
      expect(checkFrameMessage(raw, approved).ok, typeof raw).toBe(false);
    }
    const cyclic: Record<string, unknown> = {
      v: 1,
      type: "data",
      id: "r1",
      source: "calendar",
    };
    cyclic.self = cyclic;
    expect(checkFrameMessage(cyclic, approved)).toMatchObject({
      ok: false,
      reason: "not_json",
    });
    // A class instance shaped like a message is still not a plain object.
    class Fake {
      v = 1;
      type = "data";
      id = "r1";
      source = "calendar";
    }
    expect(checkFrameMessage(new Fake(), approved)).toMatchObject({
      ok: false,
      reason: "not_an_object",
    });
  });

  it("the window channel takes only the shim's ready", () => {
    expect(v("frame_to_host_window", { v: 1, type: "ready" }).ok).toBe(true);
    expect(
      v("frame_to_host_window", {
        v: 1,
        type: "data",
        id: "r1",
        source: "calendar",
      }).ok,
    ).toBe(false);
    expect(v("frame_to_host_window", { v: 1, type: "ready", x: 1 }).ok).toBe(
      false,
    );
  });
});

describe("host → frame: only init, result, update, theme (and error)", () => {
  it("accepts each well-formed message", () => {
    for (const m of [
      { v: 1, type: "init", app: "today", version: 3, theme: "dark" },
      {
        v: 1,
        type: "result",
        id: "r1",
        source: "calendar",
        state: "fresh",
        data: { items: [{ title: "Standup" }] },
        fetched_at: "2026-11-13T10:00:00+00:00",
        stale: false,
        reason: null,
      },
      {
        v: 1,
        type: "update",
        source: "inbox",
        state: "failed",
        data: null,
        fetched_at: null,
        stale: true,
        reason: "Gmail did not answer",
      },
      { v: 1, type: "theme", theme: "light" },
      { v: 1, type: "error", id: "r1", reason: "source_not_approved" },
    ]) {
      expect(isValidHostMessage(m), JSON.stringify(m)).toBe(true);
    }
  });

  it("refuses a forged or malformed host message", () => {
    for (const m of [
      {
        v: 1,
        type: "init",
        app: "today",
        version: 3,
        theme: "dark",
        token: "x",
      },
      { v: 1, type: "init", app: "Today!", version: 3, theme: "dark" },
      { v: 1, type: "theme", theme: "sepia" },
      {
        v: 1,
        type: "result",
        id: "r1",
        source: "calendar",
        state: "hacked",
        data: null,
        fetched_at: null,
        stale: false,
      },
      {
        v: 1,
        type: "result",
        id: "r1",
        source: "calendar",
        state: "fresh",
        data: null,
        fetched_at: null,
      },
      { v: 1, type: "eval", code: "alert(1)" },
      { v: 1, type: "data", id: "r1", source: "calendar" },
    ]) {
      expect(isValidHostMessage(m), JSON.stringify(m)).toBe(false);
    }
  });

  it("builds results field by field: nothing else the bridge sent rides along", () => {
    const m = buildResult(
      "result",
      "calendar",
      {
        source: "calendar",
        state: "fresh",
        data: { items: [] },
        fetched_at: "2026-11-13T10:00:00+00:00",
        stale: false,
        // A field the bridge must never send; the host must never forward.
        ...({ token: "SECRET", csrf: "CSRF" } as object),
      },
      "r9",
    );
    expect(Object.keys(m).sort()).toEqual(
      [
        "data",
        "fetched_at",
        "id",
        "reason",
        "source",
        "stale",
        "state",
        "type",
        "v",
      ].sort(),
    );
    expect(JSON.stringify(m)).not.toContain("SECRET");
    expect(JSON.stringify(m)).not.toContain("CSRF");
  });

  it("turns an unreadable bridge answer into an honest failed result", () => {
    const m = buildResult("update", "inbox", {
      state: "hacked" as never,
      data: 1,
    });
    expect(m).toMatchObject({ type: "update", state: "failed", data: null });
    expect(isValidHostMessage(m)).toBe(true);
    const missing = buildResult("result", "inbox", null, "r1");
    expect(missing).toMatchObject({ type: "result", state: "failed" });
  });
});

describe("open: https on a catalog-declared host, or /workspace/...", () => {
  const hosts = new Set(["github.com", "mail.google.com"]);
  const origin = "https://omni.example";
  it("allows https on a declared host", () => {
    expect(
      checkOpenUrl("https://github.com/a/b/pull/1", hosts, origin),
    ).toEqual({
      ok: true,
      kind: "external",
      url: "https://github.com/a/b/pull/1",
    });
    expect(checkOpenUrl("https://GitHub.com/x", hosts, origin).ok).toBe(true);
  });
  it("allows this workspace's own paths, in place", () => {
    expect(checkOpenUrl("/workspace/projects/p1", hosts, origin)).toEqual({
      ok: true,
      kind: "internal",
      path: "/workspace/projects/p1",
    });
  });
  it("refuses everything else", () => {
    for (const url of [
      "http://github.com/a",
      "https://evil.example/",
      "https://github.com.evil.example/",
      "https://evilgithub.com/",
      "https://user:pw@github.com/",
      "https://github.com:8443/",
      "javascript:alert(1)",
      "data:text/html,<script>alert(1)</script>",
      "//evil.example/x",
      "/\\evil.example",
      "/api/apps",
      "/workspace/../api/apps",
      "https://github.com/\u0000x",
      " https://github.com/",
      "mailto:a@b.c",
      "blob:https://omni.example/1",
    ]) {
      expect(checkOpenUrl(url, hosts, origin).ok, url).toBe(false);
    }
  });
});

describe("the rate limiter", () => {
  it("allows 30 in a second and refuses the 31st, then recovers", () => {
    let t = 0;
    const limiter = new RateLimiter(30, 1000, () => t);
    for (let i = 0; i < 30; i++) expect(limiter.allow()).toBe(true);
    expect(limiter.allow()).toBe(false);
    t = 999;
    expect(limiter.allow()).toBe(false);
    t = 1000;
    expect(limiter.allow()).toBe(true);
  });
});

describe("wording", () => {
  const now = Date.parse("2026-11-13T10:10:00Z");
  it("says how long ago, never a negative or NaN", () => {
    expect(ago("2026-11-13T10:06:00Z", now)).toBe("4 min ago");
    expect(ago("2026-11-13T10:09:50Z", now)).toBe("just now");
    expect(ago("2026-11-13T07:10:00Z", now)).toBe("3 h ago");
    expect(ago("2026-11-11T10:10:00Z", now)).toBe("2 days ago");
    expect(ago("2026-11-13T11:00:00Z", now)).toBe("just now");
    expect(ago("nonsense", now)).toBe("");
    expect(ago(null, now)).toBe("");
  });
  it("never words a failure as nothing", () => {
    expect(lastStateWords("failed", null, "Gmail did not answer", now)).toBe(
      "Can't tell: Gmail did not answer",
    );
    expect(
      lastStateWords("empty", "2026-11-13T10:06:00Z", null, now),
    ).toContain("Nothing");
    expect(lastStateWords("not_connected", null, null, now)).toBe(
      "Not connected",
    );
  });
  it("groups the manifest hash for comparison", () => {
    expect(hashGroups("9f2c" + "0".repeat(60))).toBe(
      "9f2c0000 00000000 00000000 00000000 00000000 00000000 00000000 00000000",
    );
  });
});
