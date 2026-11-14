import { describe, expect, it } from "vitest";

import { designPassWords } from "@/components/workspace/code-jobs/code-job-card";

describe("the job card's design pass line", () => {
  it("counts the pass within its own request", () => {
    expect(designPassWords(1)).toBe("Design pass 1 of 3.");
    expect(designPassWords(2)).toBe("Design pass 2 of 3.");
  });
  it("says plainly when all three are used", () => {
    expect(designPassWords(3)).toBe(
      "Design pass 3 of 3: 3 of 3 design passes used. No more automatic passes.",
    );
  });
});
