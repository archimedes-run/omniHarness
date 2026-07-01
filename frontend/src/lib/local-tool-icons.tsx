/**
 * Single source of truth for LOCAL (non-connector) tool icons.
 *
 * Local MCP servers use lucide-react icons. Resolution order (see ToolIcon for
 * the connector + user-created steps that wrap this):
 *   1. explicit map for known built-ins
 *   2. keyword fallback on name/description
 *   3. generic tool icon (never a puzzle piece)
 *
 * User-created / agent-built servers are handled by ToolIcon *before* this
 * resolver via USER_CREATED_ICON, so they never fall through to the keyword
 * heuristics.
 */
import {
  CircleDot,
  Database,
  Folder,
  FolderOpen,
  Github,
  Globe,
  type LucideIcon,
  Mail,
  Plug,
  Wrench,
} from "lucide-react";

// Known built-in local servers → specific lucide icon.
const EXPLICIT: Record<string, LucideIcon> = {
  filesystem: FolderOpen,
  postgres: Database,
  github: Github,
  "github-issue-connector": CircleDot,
};

/** Bound to the user-created / agent-built MCP SOURCE (not a server name). */
export const USER_CREATED_ICON: LucideIcon = Wrench;

/** Final fallback for genuinely unclassifiable local rows (never a puzzle piece). */
export const GENERIC_TOOL_ICON: LucideIcon = Plug;

export function resolveLocalToolIcon(
  name: string,
  description = "",
): LucideIcon {
  const key = (name || "").toLowerCase();
  const explicit = EXPLICIT[key];
  if (explicit) return explicit;

  const hay = `${key} ${description.toLowerCase()}`;
  if (/post?gres|sql|\bdb\b|database/.test(hay)) return Database;
  if (/file|\bfs\b|directory/.test(hay)) return Folder;
  if (/git|repo/.test(hay)) return Github;
  if (/http|web|fetch|search/.test(hay)) return Globe;
  if (/mail|smtp/.test(hay)) return Mail;
  return GENERIC_TOOL_ICON;
}
