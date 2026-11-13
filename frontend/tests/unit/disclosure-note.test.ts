import { describe, expect, it } from "vitest";

import {
  DISCLOSURE_MARKER,
  disclosureSummary,
  splitDisclosure,
} from "@/core/disclosure";

const BLOCK =
  "\n\nAlso, for the record:\n  - I used code_job with goal=<412 chars>, project_dir='vite-counter'.";

describe("the policy layer's disclosure block (spec 009 Slice 0)", () => {
  it("moves only the block the server marked out of the reply", () => {
    const content = "The counter app is built and showing." + BLOCK;
    const split = splitDisclosure(content, {
      [DISCLOSURE_MARKER]: {
        text: BLOCK,
        items: [{ tool: "code_job", text: "I used code_job with ..." }],
      },
    });
    expect(split.body).toBe("The counter app is built and showing.");
    expect(split.items.map((i) => i.tool)).toEqual(["code_job"]);
  });

  it("never moves text by its wording: no marker, nothing moved", () => {
    const content = "Done." + BLOCK;
    expect(splitDisclosure(content, {})).toEqual({ body: content, items: [] });
  });

  it("ignores a marker whose block is not the end of the text", () => {
    const content = "Edited reply.";
    const split = splitDisclosure(content, {
      [DISCLOSURE_MARKER]: { text: BLOCK, items: [{ tool: "x", text: "" }] },
    });
    expect(split).toEqual({ body: content, items: [] });
  });

  it("puts every action on one line, first-occurrence order, repeats counted", () => {
    expect(disclosureSummary([{ tool: "code_job", text: "" }])).toBe(
      "code_job",
    );
    expect(
      disclosureSummary([
        { tool: "code_job", text: "" },
        { tool: "ledger_apply", text: "" },
        { tool: "write_file", text: "" },
        { tool: "ledger_apply", text: "" },
      ]),
    ).toBe("code_job, ledger_apply \u00d72, write_file");
    expect(
      disclosureSummary([
        { tool: "ledger_apply", text: "" },
        { tool: "ledger_apply", text: "" },
        { tool: "ledger_apply", text: "" },
      ]),
    ).toBe("ledger_apply \u00d73");
  });
});
