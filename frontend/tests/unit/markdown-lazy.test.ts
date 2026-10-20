import { describe, expect, it } from "vitest";

import { needsCode, needsMath } from "@/core/streamdown/lazy-plugins";

describe("which messages load the highlighter or the math renderer", () => {
  it("loads code highlighting only for a fenced block", () => {
    expect(needsCode("```ts\nconst x = 1\n```")).toBe(true);
    expect(needsCode("text\n  ~~~\ncode\n~~~")).toBe(true);
    expect(needsCode("inline `code` is not a fence")).toBe(false);
    expect(needsCode("plain prose")).toBe(false);
  });

  it("loads math for math, not for prices", () => {
    expect(needsMath("the area is $\\pi r^2$.")).toBe(true);
    expect(needsMath("$$E = mc^2$$")).toBe(true);
    expect(needsMath("\\(x\\) and \\[y\\]")).toBe(true);
    expect(needsMath("It costs $5 or $10.")).toBe(false);
    expect(needsMath("$5 to $ 10")).toBe(false);
    expect(needsMath("no dollars here")).toBe(false);
  });
});
