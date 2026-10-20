"use client";

import { SearchIcon } from "lucide-react";
import { useEffect, useState, type KeyboardEvent } from "react";

import { SidebarTrigger } from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { PANEL_ICONS, PANEL_IDS, panelLabel, preloadPanel } from "./panels";
import { useShell } from "./shell-context";

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

const BUTTON =
  "text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-ring flex h-11 min-w-11 items-center justify-center gap-1.5 rounded-lg px-2.5 text-[13px] outline-none focus-visible:ring-2 md:h-9 md:min-w-9 md:px-3";

/**
 * The capsule (Feature 006): a pill at the top centre of every workspace
 * page. Agents · Skills · Automations · Tasks each open their panel as a
 * sheet over the page; ⌘K opens the command palette. At phone width the
 * labels go and the icons stay, each a 44 px target.
 */
export function Capsule() {
  const { t } = useI18n();
  const { panel, openPanel, openPalette, paletteOpen } = useShell();
  const [isMac, setIsMac] = useState(true);
  useEffect(() => {
    setIsMac(navigator.userAgent.includes("Mac"));
  }, []);

  return (
    <div
      className="relative flex h-14 shrink-0 items-center justify-center px-2"
      data-testid="capsule-bar"
    >
      <SidebarTrigger
        className="absolute left-2 size-11 md:hidden"
        aria-label={t.shell.openSidebar}
      />
      <div
        role="toolbar"
        aria-label={t.shell.tools}
        aria-orientation="horizontal"
        data-testid="capsule"
        onKeyDown={moveFocus}
        className="bg-card border-border flex items-center gap-0.5 rounded-xl border p-1 shadow-xs"
      >
        {PANEL_IDS.map((id) => {
          const Icon = PANEL_ICONS[id];
          const label = panelLabel(t, id);
          return (
            <button
              key={id}
              type="button"
              data-capsule={id}
              aria-haspopup="dialog"
              aria-expanded={panel === id}
              aria-label={label}
              className={cn(
                BUTTON,
                panel === id && "bg-accent text-accent-foreground",
              )}
              onPointerEnter={() => preloadPanel(id)}
              onFocus={() => preloadPanel(id)}
              onClick={(event) => openPanel(id, event.currentTarget)}
            >
              <Icon className="size-4" aria-hidden />
              <span className="hidden sm:inline" aria-hidden>
                {label}
              </span>
            </button>
          );
        })}
        <span className="bg-border mx-1 h-5 w-px" aria-hidden />
        <button
          type="button"
          data-capsule="palette"
          aria-haspopup="dialog"
          aria-expanded={paletteOpen}
          aria-label={t.shell.searchEverything}
          aria-keyshortcuts="Meta+K Control+K /"
          className={cn(BUTTON, "bg-muted text-muted-foreground text-xs")}
          onClick={(event) => openPalette(event.currentTarget)}
        >
          <SearchIcon className="size-3.5" aria-hidden />
          <span className="hidden sm:inline" aria-hidden>
            {isMac ? "⌘K" : "Ctrl K"}
          </span>
        </button>
      </div>
    </div>
  );
}
