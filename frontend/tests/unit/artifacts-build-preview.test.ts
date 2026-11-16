import { describe, expect, it } from "vitest";

import {
  registerPreview,
  type BuildPreviewDetails,
} from "@/core/artifacts/build-preview";
const current: BuildPreviewDetails = {
  threadId: "chat",
  jobId: "b",
  publishedAt: 200,
  title: "Today",
  sample: true,
  appId: "today",
};
describe("published build metadata", () => {
  it("keeps a newer registered sample when an older generic job responds last", () => {
    const first = registerPreview({}, "/output/index.html", current);
    const late = {
      ...current,
      jobId: "a",
      publishedAt: 100,
      title: "Old build",
      sample: false,
      appId: undefined,
    };
    expect(registerPreview(first, "/output/index.html", late)).toBe(first);
    expect(first["/output/index.html"]).toEqual(current);
  });
  it("accepts newer publication metadata regardless of response order", () => {
    const old = { ...current, publishedAt: 100, sample: false };
    expect(registerPreview({ path: old }, "path", current).path).toEqual(
      current,
    );
  });
  it("does not compare publication times across different chats", () => {
    const next = { ...current, threadId: "other-chat", publishedAt: 100 };
    expect(registerPreview({ path: current }, "path", next).path).toEqual(next);
  });
  it("breaks equal-time ties deterministically and ignores unchanged polling", () => {
    const first = { path: current };
    expect(registerPreview(first, "path", { ...current, jobId: "a" })).toBe(
      first,
    );
    expect(registerPreview(first, "path", { ...current })).toBe(first);
  });
});
