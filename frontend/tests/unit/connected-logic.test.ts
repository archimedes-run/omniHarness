import { describe, expect, it } from "vitest";

import {
  countSources,
  sourceStatus,
  transportOf,
} from "@/components/workspace/connections/connected-logic";
import type { ToolSource } from "@/core/tool-sources/types";

const src = (state: ToolSource["state"], kind: ToolSource["kind"]) =>
  ({
    id: `${kind}:${state}`,
    name: state,
    kind,
    state,
    tool_count: null,
    error: null,
    selected: null,
  }) as ToolSource;

describe("MCP Suite > Connected counts", () => {
  it("puts every source in exactly one count, and keeps can't-tell apart", () => {
    const sources = [
      src("live", "local"),
      src("authorised", "connector"),
      src("authorised-not-selected", "connector"),
      src("unreachable", "local"),
      src("not-authorised", "connector"),
      src("not-configured", "local"),
      src("disabled", "local"),
      src("not-loaded", "local"),
    ];
    const c = countSources(sources);
    expect(c).toEqual({
      live: 3,
      unreachable: 1,
      notConnected: 2,
      off: 1,
      unknown: 1,
    });
    expect(c.live + c.unreachable + c.notConnected + c.off + c.unknown).toBe(
      sources.length,
    );
  });

  it("never calls a source that was not loaded off or live", () => {
    expect(sourceStatus(src("not-loaded", "local")).label).toBe(
      "Can't tell yet",
    );
    expect(sourceStatus(src("unreachable", "local")).tone).toBe("warn");
  });
});

describe("where a server runs", () => {
  it("reads local and remote from the URL, stdio as local", () => {
    expect(
      transportOf({
        type: "sse",
        url: "http://host.docker.internal:18101/sse",
      }),
    ).toBe("Local · SSE");
    expect(
      transportOf({ type: "http", url: "https://mcp.example.com/x" }),
    ).toBe("Remote · HTTP");
    expect(transportOf({ command: "npx" })).toBe("Local · stdio");
    expect(transportOf(undefined)).toBe("—");
  });
});
