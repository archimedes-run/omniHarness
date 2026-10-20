import { readFileSync } from "fs";
import { join } from "path";

import { describe, expect, it } from "vitest";

import { providerLink, safeField, safeLines } from "@/core/display/safe";

const cases = JSON.parse(
  readFileSync(join(__dirname, "display-safe-cases.json"), "utf-8"),
) as {
  field: [string, string][];
  lines: [string, string][];
  links: [string, string, boolean][];
};

describe("the frontend display sanitiser mirrors the backend's", () => {
  it.each(cases.field)("field %j", (input, expected) => {
    expect(safeField(input)).toBe(expected);
    expect(safeField(safeField(input))).toBe(expected);
  });
  it.each(cases.lines)("lines %j", (input, expected) => {
    expect(safeLines(input)).toBe(expected);
  });
  it.each(cases.links)("link %s %j live=%s", (source, url, live) => {
    expect(providerLink(source, url) === url).toBe(live);
  });
});
