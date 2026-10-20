import type { StatusTone } from "@/components/workspace/page-kit";
import { describeState } from "@/core/tool-sources/logic";
import type { ToolSource } from "@/core/tool-sources/types";

export interface SourceCounts {
  live: number;
  unreachable: number;
  notConnected: number;
  off: number;
  /** Configured, never loaded in this worker: can't tell, not "off". */
  unknown: number;
}

/** The board's counts. Every source lands in exactly one of them. */
export function countSources(sources: ToolSource[]): SourceCounts {
  const counts: SourceCounts = {
    live: 0,
    unreachable: 0,
    notConnected: 0,
    off: 0,
    unknown: 0,
  };
  for (const s of sources) {
    switch (s.state) {
      case "live":
      case "authorised":
      case "authorised-selected":
      case "authorised-not-selected":
        counts.live += 1;
        break;
      case "unreachable":
        counts.unreachable += 1;
        break;
      case "not-authorised":
      case "not-configured":
        counts.notConnected += 1;
        break;
      case "disabled":
        counts.off += 1;
        break;
      case "not-loaded":
        counts.unknown += 1;
        break;
    }
  }
  return counts;
}

/** A source's status in one word or two, its tone, and what it means. */
export function sourceStatus(source: ToolSource): {
  label: string;
  tone: StatusTone;
  meaning: string;
} {
  const { meaning } = describeState(source);
  switch (source.state) {
    case "live":
      return { label: "Live", tone: "good", meaning };
    case "authorised":
      return {
        label: "Live",
        tone: "good",
        meaning: "Connected · each chat chooses it",
      };
    case "authorised-selected":
      return { label: "Live", tone: "good", meaning: "On in this chat" };
    case "authorised-not-selected":
      return { label: "Live", tone: "good", meaning: "Not on in this chat" };
    case "unreachable":
      return { label: "Unreachable", tone: "warn", meaning };
    case "disabled":
      return { label: "Off", tone: "muted", meaning };
    case "not-configured":
      return { label: "Not configured", tone: "muted", meaning };
    case "not-authorised":
      return { label: "Not connected", tone: "muted", meaning };
    default:
      return { label: "Can't tell yet", tone: "muted", meaning };
  }
}

const LOCAL_HOST =
  /^(localhost|127\.|0\.0\.0\.0|host\.docker\.internal|\[::1\])/;

/** "Local · SSE", "Remote · HTTP", "Local · stdio", or "—" with no entry. */
export function transportOf(
  entry: Record<string, unknown> | undefined,
): string {
  if (!entry) return "—";
  const type = typeof entry.type === "string" ? entry.type : "stdio";
  if (type === "stdio") return "Local · stdio";
  const url = typeof entry.url === "string" ? entry.url : "";
  let host = "";
  try {
    host = new URL(url).hostname;
  } catch {
    host = "";
  }
  const where = host === "" ? "—" : LOCAL_HOST.test(host) ? "Local" : "Remote";
  const kind =
    type === "sse" ? "SSE" : /http/i.test(type) ? "HTTP" : type.toUpperCase();
  return `${where} · ${kind}`;
}
