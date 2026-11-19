import { describe, expect, it } from "vitest";

import { artifactDisplayName } from "@/core/artifacts/utils";
import { getFileName } from "@/core/utils/files";

describe("artifact display name", () => {
  it("names a written file by its decoded file name, not the step query", () => {
    const value = new URL(
      "write-file:/mnt/user-data/outputs/my report.md?message_id=m1&tool_call_id=c1",
    ).toString();
    expect(artifactDisplayName(value, [], getFileName)).toBe("my report.md");
  });

  it("names a plain path by its file name", () => {
    expect(
      artifactDisplayName("/mnt/user-data/outputs/a/b.csv", [], getFileName),
    ).toBe("b.csv");
  });
});
