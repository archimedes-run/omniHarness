import type { StatusTone } from "@/components/workspace/page-kit";
import type { BuildState } from "@/core/mcp-studio/types";

export function buildStateTone(state: BuildState | undefined): StatusTone {
  switch (state) {
    case "enabled":
      return "good";
    case "awaiting_approval":
      return "warn";
    case "tests_failed":
    case "stalled":
      return "bad";
    default:
      return "muted";
  }
}
