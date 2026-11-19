import { describe, expect, it } from "vitest";

import { validateNextParam } from "@/core/auth/next-param";

const origin = "https://example.test";

describe("login return path", () => {
  it.each([
    ["/\\host"],
    ["/\\/host"],
    ["//host"],
    ["\\\\host"],
    // searchParams.get() decodes %5C, so these are the decoded forms of /%5Chost
    [decodeURIComponent("/%5Chost")],
    [decodeURIComponent("/%5C%5Chost")],
    ["/\thost"],
    ["/\t/host"],
    ["/workspace\n/apps"],
    ["/workspace/\u0000"],
    ["/workspace/\u007f"],
    ["https://elsewhere.test/"],
    ["javascript:alert(1)"],
    ["workspace"],
    [""],
    [null],
  ])("rejects %j", (next) => {
    expect(validateNextParam(next, origin)).toBeNull();
  });

  it.each([
    ["/workspace/apps/today", "/workspace/apps/today"],
    ["/workspace/chats/x?y=1#z", "/workspace/chats/x?y=1#z"],
    // still-encoded backslash is an ordinary path segment on this origin
    ["/%5Chost", "/%5Chost"],
  ])("accepts %j", (next, expected) => {
    expect(validateNextParam(next, origin)).toBe(expected);
  });
});
