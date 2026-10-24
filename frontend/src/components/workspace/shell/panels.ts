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
  /** Which panel the sheet shows (the Studio serves both agents and skills). */
  panel: PanelId;
  /**
   * A panel with work in progress registers a guard; Esc, a click outside and
   * the close button ask it first. It returns true when it handled the close
   * itself (an unsaved-changes prompt, an inner editor closing).
   */
  setCloseGuard: (guard: CloseGuard | null) => void;
}

export type CloseGuard = (reason: "escape" | "outside") => boolean;

/** Panels that draw their own header, close button and scrolling (the
 * Agent & Skill Studio, 006-G). They share one component, kept mounted when
 * the person switches between them. */
export const SELF_CHROME_PANELS: ReadonlySet<PanelId> = new Set([
  "agents",
  "skills",
]);

type Loader = () => Promise<{ default: ComponentType<PanelProps> }>;

export const PANEL_LOADERS: Record<PanelId, Loader> = {
  agents: () => import("./panels/studio-panel"),
  skills: () => import("./panels/studio-panel"),
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
