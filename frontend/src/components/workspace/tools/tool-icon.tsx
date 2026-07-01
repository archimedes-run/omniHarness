/**
 * Shared tool icon. One resolver for every place a tool renders (picker rows,
 * pinned/enabled list, tool-call chips) so nothing ever shows a puzzle piece.
 *
 * Resolution order:
 *   1. connector toolkit slug        → brand icon (IntegrationIcon)
 *   2. user-created / agent-built MCP → crossed-tools icon (bound to SOURCE)
 *   3. known built-in local server   → its mapped lucide icon
 *   4. keyword fallback              → lucide icon
 *   5. anything unmatched            → generic tool icon (Plug)
 */
import { createElement } from "react";

import { IntegrationIcon } from "@/components/workspace/tools/integration-icon";
import {
  resolveLocalToolIcon,
  USER_CREATED_ICON,
} from "@/lib/local-tool-icons";
import { cn } from "@/lib/utils";

export type ToolIconSource = "local" | "connector";
export type ToolIconOrigin = "builtin" | "user";

export function ToolIcon({
  source,
  name,
  slug,
  origin = "builtin",
  description = "",
  size = 20,
  className,
}: {
  source: ToolIconSource;
  name: string;
  slug?: string | null;
  origin?: ToolIconOrigin;
  description?: string;
  size?: number;
  className?: string;
}) {
  const box = cn(
    "flex shrink-0 items-center justify-center overflow-hidden rounded-lg bg-muted",
    className,
  );
  const boxStyle = { width: size + 12, height: size + 12 };

  if (source === "connector") {
    return (
      <span className={box} style={boxStyle}>
        <IntegrationIcon slug={slug} size={size} label={name} />
      </span>
    );
  }

  // Local: user-created MCP source wins over name-based resolution.
  const iconComponent =
    origin === "user"
      ? USER_CREATED_ICON
      : resolveLocalToolIcon(name, description);
  return (
    <span className={box} style={boxStyle}>
      {createElement(iconComponent, {
        style: { width: size, height: size },
        className: "text-foreground/80",
        "aria-label": name,
      })}
    </span>
  );
}
