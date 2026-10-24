"use client";

import {
  BarChart3Icon,
  BookOpenIcon,
  CalendarIcon,
  CodeIcon,
  CompassIcon,
  DatabaseIcon,
  EyeIcon,
  FolderIcon,
  GlobeIcon,
  HandIcon,
  HeartIcon,
  LayersIcon,
  ListIcon,
  MailIcon,
  MegaphoneIcon,
  PenLineIcon,
  QuoteIcon,
  RocketIcon,
  SearchIcon,
  ShieldIcon,
  SmileIcon,
  SparklesIcon,
  StarIcon,
  TableIcon,
  TargetIcon,
  TerminalIcon,
  WandSparklesIcon,
  ZapIcon,
  type LucideIcon,
} from "lucide-react";
import { createElement, type ReactNode } from "react";

import { avatarMeta, avatarSrc } from "@/core/agents";
import type { AgentStatus, CatalogIntegration, Tier } from "@/core/studio";

import { useStudioCopy } from "./copy";

/** Class names, joined. (Not template strings: the Tailwind Prettier plugin
 * trims the space a conditional fragment like `" on"` starts with.) */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/** The skill icon grid, in the design's order (SKILL_ICONS on the server). */
export const SKILL_GLYPHS: [string, LucideIcon][] = [
  ["list", ListIcon],
  ["quote", QuoteIcon],
  ["search", SearchIcon],
  ["code", CodeIcon],
  ["pen", PenLineIcon],
  ["smile", SmileIcon],
  ["rocket", RocketIcon],
  ["chart", BarChart3Icon],
  ["target", TargetIcon],
  ["star", StarIcon],
  ["calendar", CalendarIcon],
  ["mail", MailIcon],
  ["wand", WandSparklesIcon],
  ["folder", FolderIcon],
  ["database", DatabaseIcon],
  ["terminal", TerminalIcon],
  ["globe", GlobeIcon],
  ["heart", HeartIcon],
  ["compass", CompassIcon],
  ["table", TableIcon],
  ["layers", LayersIcon],
  ["mega", MegaphoneIcon],
  ["shield", ShieldIcon],
  ["book", BookOpenIcon],
];
const GLYPH = new Map(SKILL_GLYPHS);

/** Stable default icon and colour for a skill that has none saved. */
export function skillLook(
  name: string,
  icon: string | null | undefined,
  color: number | null | undefined,
): { icon: string; color: number } {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return {
    icon:
      icon && GLYPH.has(icon)
        ? icon
        : SKILL_GLYPHS[h % SKILL_GLYPHS.length]![0],
    color: typeof color === "number" && color >= 0 && color < 8 ? color : h % 8,
  };
}

export function Glyph({
  icon,
  color,
  size = 18,
  box,
  className = "",
}: {
  icon: string;
  color: number;
  size?: number;
  /** The tile's side in px (default from CSS: 36). */
  box?: number;
  className?: string;
}) {
  return (
    <span
      className={`glyph t-${color} ${className}`}
      style={box ? { width: box, height: box } : undefined}
      aria-hidden
    >
      {createElement(GLYPH.get(icon) ?? StarIcon, { size })}
    </span>
  );
}

export function GlyphIcon({
  icon,
  size = 16,
}: {
  icon: string;
  size?: number;
}) {
  return createElement(GLYPH.get(icon) ?? StarIcon, {
    size,
    "aria-hidden": true,
  });
}

/** An avatar image (known ids only). */
export function Av({
  id,
  size,
  alt = "",
}: {
  id: string;
  size: number;
  alt?: string;
}) {
  return (
    <img
      className="av"
      src={avatarSrc(id)}
      width={size}
      height={size}
      alt={alt}
      style={{ width: size, height: size, background: avatarMeta(id).bg }}
      draggable={false}
    />
  );
}

/** A labelled switch (36x20), with "mixed" for a partly-on integration. */
export function Switch({
  checked,
  onChange,
  label,
  disabled,
  describedBy,
  testId,
}: {
  checked: boolean | "mixed";
  onChange: () => void;
  label: string;
  disabled?: boolean;
  describedBy?: string;
  testId?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      className="switch"
      aria-checked={checked === "mixed" ? "mixed" : checked}
      aria-label={label}
      aria-describedby={describedBy}
      disabled={disabled}
      onClick={onChange}
      data-testid={testId}
    />
  );
}

const TIER_ICON: Record<Tier, LucideIcon> = {
  1: EyeIcon,
  2: ZapIcon,
  3: HandIcon,
};

/** A tool's tier, as the policy classifier decided it. */
export function TierBadge({ tier }: { tier: Tier | null }) {
  const c = useStudioCopy().agent;
  if (tier === null)
    return (
      <span className="tier t0" title={c.tierNoneHelp}>
        {c.tier.none}
      </span>
    );
  const Icon = TIER_ICON[tier];
  return (
    <span className={`tier t${tier}`} data-tier={tier}>
      <Icon size={12} aria-hidden />
      {c.tier[tier]}
    </span>
  );
}

const STATUS_TONE: Record<AgentStatus, string> = {
  active: "good",
  scheduled: "accent",
  draft: "muted",
  ondemand: "muted",
  paused: "warn",
};

export function StatusPill({ status }: { status: AgentStatus }) {
  const c = useStudioCopy().agents;
  return (
    <span
      className={`pill ${STATUS_TONE[status]}`}
      title={c.statusHelp[status]}
      data-status={status}
    >
      <span className="d" />
      {c.status[status]}
    </span>
  );
}

export function Pill({
  tone,
  dot,
  children,
}: {
  tone: "good" | "warn" | "bad" | "accent" | "muted";
  dot?: boolean;
  children: ReactNode;
}) {
  return (
    <span className={`pill ${tone}`}>
      {dot ? <span className="d" /> : null}
      {children}
    </span>
  );
}

const MONO: Record<string, [string, string]> = {
  "connector:GMAIL": ["Gm", "3"],
  "connector:GITHUB": ["GH", "lead"],
  "connector:GOOGLECALENDAR": ["31", "0"],
  "connector:GOOGLEDRIVE": ["Dr", "5"],
  "connector:SLACK": ["Sl", "2"],
  "connector:NOTION": ["N", "lead"],
  "connector:LINEAR": ["Li", "1"],
  "connector:OUTLOOK": ["Ol", "0"],
  "builtin:web": ["W", "7"],
  "builtin:ledger": ["Tk", "6"],
  "builtin:file:read": ["Rf", "6"],
  "builtin:file:write": ["Wf", "4"],
  "builtin:bash": [">_", "lead"],
  "builtin:workspace": ["Ws", "1"],
  "local:filesystem": ["fs", "6"],
  "local:postgres": ["pg", "0"],
  "local:session-watcher": ["sw", "7"],
  "local:github": ["GH", "lead"],
  "local:gmail": ["Gm", "3"],
  "local:googlecalendar": ["31", "0"],
};

export function monoFor(
  i: Pick<CatalogIntegration, "id" | "name">,
): [string, string] {
  const known = MONO[i.id];
  if (known) return known;
  const words = i.name
    .replace(/[-_:]+/g, " ")
    .trim()
    .split(/\s+/);
  const text =
    words.length > 1
      ? (words[0]![0]! + words[1]![0]!).toLowerCase()
      : (words[0] ?? "?").slice(0, 2).toLowerCase();
  let h = 0;
  for (const ch of i.id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return [text, String(h % 8)];
}

/** An integration's monogram tile. */
export function Mono({
  integration,
  lg,
}: {
  integration: Pick<CatalogIntegration, "id" | "name">;
  lg?: boolean;
}) {
  const [text, tint] = monoFor(integration);
  return (
    <span className={cx("mono", `t-${tint}`, lg && "lg")} aria-hidden>
      {text}
    </span>
  );
}

export function DraftedTag({ show }: { show: boolean }) {
  const c = useStudioCopy();
  if (!show) return null;
  return (
    <span className="drafted">
      <SparklesIcon size={12} aria-hidden />
      {c.drafted}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd>{children}</kbd>;
}

export function Spinner() {
  return <span className="spin" aria-hidden />;
}
