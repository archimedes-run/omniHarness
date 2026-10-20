"use client";

import { SearchIcon } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useState, type KeyboardEvent } from "react";

import { SidebarTrigger } from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { Tooltip } from "../tooltip";

import { PANEL_ICONS, PANEL_IDS, panelLabel, preloadPanel } from "./panels";
import { useShell } from "./shell-context";
import { defaultTitle } from "./titles";

/** Arrow keys move between the capsule's buttons (WAI-ARIA toolbar). */
function moveFocus(event: KeyboardEvent<HTMLDivElement>) {
  const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
  if (!keys.includes(event.key)) return;
  const buttons = Array.from(
    event.currentTarget.querySelectorAll<HTMLButtonElement>("button"),
  );
  const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
  if (index < 0) return;
  event.preventDefault();
  const next =
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? buttons.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) %
          buttons.length;
  buttons[next]?.focus();
}

// Chat-Bar-v2.dc.html: 34 px buttons, 17 px radius, 18 px icon + 14 px label.
// At phone width each is a 44 px target.
const BUTTON =
  "text-foreground-2 hover:bg-surface-raised hover:text-foreground focus-visible:ring-ring flex h-11 min-w-11 items-center justify-center gap-2 rounded-[22px] px-3 text-sm outline-none focus-visible:ring-2 md:h-[34px] md:min-w-[34px] md:rounded-[17px] @[900px]/topbar:px-4";

/**
 * The top bar (Feature 006, Chat-Bar-v2.dc.html): a three-column grid, so the
 * capsule sits on the true centre of the main area whatever the title's
 * length or the sidebar's state. Left: the page or thread title. Centre: the
 * capsule, Agents · Skills · Automations · Tasks, each opening its panel as a
 * sheet over the page. Right: Search, which opens the ⌘K palette.
 *
 * Below 900 px of main area (a container query, so the sidebar counts) the
 * capsule shows icons only, each named and with a tooltip.
 */
export function Capsule() {
  const { t } = useI18n();
  const pathname = usePathname();
  const { panel, openPanel, openPalette, paletteOpen, title } = useShell();
  const [isMac, setIsMac] = useState(true);
  useEffect(() => {
    setIsMac(navigator.userAgent.includes("Mac"));
  }, []);
  const shown = title ?? defaultTitle(pathname);

  return (
    <div className="@container/topbar shrink-0" data-testid="capsule-bar">
      <header className="grid h-16 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-4 px-2 md:px-6">
        <div className="flex min-w-0 items-center gap-1">
          <SidebarTrigger
            className="size-11 shrink-0 md:hidden"
            aria-label={t.shell.openSidebar}
          />
          <span
            className="text-muted-foreground truncate text-[13px]"
            data-testid="topbar-title"
            title={shown}
          >
            {shown}
          </span>
        </div>
        <div
          role="toolbar"
          aria-label={t.shell.tools}
          aria-orientation="horizontal"
          data-testid="capsule"
          onKeyDown={moveFocus}
          className="bg-card border-border flex items-center gap-1 rounded-[22px] border p-1 shadow-md md:h-11"
        >
          {PANEL_IDS.map((id) => {
            const Icon = PANEL_ICONS[id];
            const label = panelLabel(t, id);
            const active = panel === id;
            return (
              <Tooltip key={id} content={label}>
                <button
                  type="button"
                  data-capsule={id}
                  aria-haspopup="dialog"
                  aria-expanded={active}
                  aria-pressed={active}
                  aria-label={label}
                  className={cn(
                    BUTTON,
                    active &&
                      "bg-primary-subtle text-foreground hover:bg-primary-subtle font-medium",
                  )}
                  onPointerEnter={() => preloadPanel(id)}
                  onFocus={() => preloadPanel(id)}
                  onClick={(event) => openPanel(id, event.currentTarget)}
                >
                  <Icon className="size-[18px] shrink-0" aria-hidden />
                  <span className="hidden @[900px]/topbar:inline">{label}</span>
                </button>
              </Tooltip>
            );
          })}
        </div>
        <div className="flex min-w-0 justify-end">
          <button
            type="button"
            data-testid="search-button"
            aria-haspopup="dialog"
            aria-expanded={paletteOpen}
            aria-label={`${t.shell.searchEverything} (${isMac ? "Command K" : "Control K"})`}
            aria-keyshortcuts="Meta+K Control+K /"
            className="bg-sidebar border-border text-muted-foreground hover:text-foreground focus-visible:ring-ring flex h-11 min-w-11 shrink-0 items-center justify-center gap-2.5 rounded-[10px] border px-2.5 text-[13px] outline-none focus-visible:ring-2 md:h-9 md:min-w-9 @[640px]/topbar:pr-2.5 @[640px]/topbar:pl-3"
            onClick={(event) => openPalette(event.currentTarget)}
          >
            <SearchIcon className="size-[15px] shrink-0" aria-hidden />
            <span className="hidden @[640px]/topbar:inline">Search</span>
            <kbd
              className="bg-surface-raised border-border-strong text-foreground-2 hidden rounded-md border px-1.5 font-sans text-xs @[640px]/topbar:inline"
              aria-hidden
            >
              {isMac ? "⌘K" : "Ctrl+K"}
            </kbd>
          </button>
        </div>
      </header>
    </div>
  );
}
