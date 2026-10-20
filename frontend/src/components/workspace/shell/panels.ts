import {
  type LucideIcon,
  SparklesIcon,
  SquareCheckIcon,
  UsersIcon,
  ZapIcon,
} from "lucide-react";
import type { ComponentType } from "react";

import type { Translations } from "@/core/i18n/locales/types";

/**
 * The capsule's panels (Feature 006, Phase 1). Each opens as a large sheet
 * over the current page, named in the URL as `?panel=<id>`.
 *
 * Phase 1 content is the existing page; later phases redesign each one. The
 * content is a dynamic import: no page pays for a panel until the user
 * reaches for it (hover, focus or open). bundle-budget.spec.ts holds that.
 */
export const PANEL_IDS = ["agents", "skills", "automations", "tasks"] as const;
export type PanelId = (typeof PANEL_IDS)[number];

export const PANEL_PARAM = "panel";

export function isPanelId(value: string | null | undefined): value is PanelId {
  return PANEL_IDS.includes(value as PanelId);
}

export interface PanelProps {
  onClose: () => void;
}

type Loader = () => Promise<{ default: ComponentType<PanelProps> }>;

export const PANEL_LOADERS: Record<PanelId, Loader> = {
  agents: () => import("./panels/agents-panel"),
  skills: () => import("./panels/skills-panel"),
  automations: () => import("./panels/automations-panel"),
  tasks: () => import("./panels/tasks-panel"),
};

/** Start fetching a panel's code before it is opened (hover, focus). */
export function preloadPanel(id: PanelId) {
  void PANEL_LOADERS[id]().catch(() => undefined);
}

export const PANEL_ICONS: Record<PanelId, LucideIcon> = {
  agents: UsersIcon,
  skills: SparklesIcon,
  automations: ZapIcon,
  tasks: SquareCheckIcon,
};

export function panelLabel(t: Translations, id: PanelId): string {
  return t.shell[id];
}

/** The current URL with the panel param set (or removed), path and other
 * params kept. */
export function urlWithPanel(panel: PanelId | null): string {
  const url = new URL(window.location.href);
  if (panel) url.searchParams.set(PANEL_PARAM, panel);
  else url.searchParams.delete(PANEL_PARAM);
  return `${url.pathname}${url.search}${url.hash}`;
}
