import { describe, expect, it } from "vitest";

import { parseLedgerResult } from "@/core/ledger/api";

describe("a ledger write's disclosure carries its Undo", () => {
  it("finds the write id an unconfirmed write names", () => {
    expect(
      parseLedgerResult(
        "Added T-1 “Draft” to Launch. [undo w-0123456789abcdef]",
      ),
    ).toEqual({
      text: "Added T-1 “Draft” to Launch.",
      writeId: "w-0123456789abcdef",
    });
  });

  it("offers no Undo for a confirmed write or a suggestion", () => {
    expect(parseLedgerResult("Added T-1 “Draft” to Launch.").writeId).toBe(
      null,
    );
    expect(
      parseLedgerResult("This is a suggestion: it came from something I read")
        .writeId,
    ).toBe(null);
  });
});
