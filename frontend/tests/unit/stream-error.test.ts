import { describe, expect, it } from "vitest";

import {
  STREAM_FAILED,
  streamErrorToast,
} from "../../src/core/threads/stream-error";

describe("streamErrorToast", () => {
  it("is quiet when the run is no longer live (reload after a restart)", () => {
    for (const run of ["a9afaaa6-1111-2222-3333-444455556666", "done-run"]) {
      expect(
        streamErrorToast(
          new Error(`HTTP 404: {"detail":"Run ${run} not found"}`),
        ),
      ).toBeNull();
    }
  });

  it("never shows a raw HTTP body", () => {
    for (const raw of [
      'HTTP 500: {"detail":"Internal Server Error"}',
      'HTTP 404: {"detail":"Thread t not found"}',
      { message: 'HTTP 502: {"error":"bad gateway"}' },
      'Unexpected response {"detail":"x"}',
    ]) {
      const shown = streamErrorToast(raw);
      expect(shown).toBe(STREAM_FAILED);
      expect(shown).not.toContain("{");
    }
  });

  it("keeps a plain message", () => {
    expect(streamErrorToast(new Error("Network error"))).toBe("Network error");
    expect(streamErrorToast(undefined)).toBe("Request failed.");
  });
});
