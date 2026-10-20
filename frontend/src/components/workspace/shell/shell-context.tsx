"use client";

import { useSearchParams } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  PANEL_PARAM,
  isPanelId,
  preloadPanel,
  urlWithPanel,
  type PanelId,
} from "./panels";

interface ShellContextValue {
  /** The open panel, read from `?panel=` (null when none or unknown). */
  panel: PanelId | null;
  openPanel: (id: PanelId, returnFocusTo?: HTMLElement | null) => void;
  closePanel: () => void;
  /** Where focus goes when the panel closes. */
  panelReturnFocus: () => HTMLElement | null;
  paletteOpen: boolean;
  openPalette: (returnFocusTo?: HTMLElement | null) => void;
  setPaletteOpen: (open: boolean) => void;
  paletteReturnFocus: () => HTMLElement | null;
  /** The top bar's title, set by the page (null: derived from the path). */
  title: string | null;
  setTitle: (title: string | null) => void;
}

const ShellContext = createContext<ShellContextValue | null>(null);

function here() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function activeElement(): HTMLElement | null {
  const el = document.activeElement;
  return el instanceof HTMLElement && el !== document.body ? el : null;
}

/**
 * The app shell's state: which capsule panel is open and whether the command
 * palette is.
 *
 * The panel lives in the URL so it can be linked. It is written with the
 * native History API, which Next keeps in sync with useSearchParams without a
 * navigation: the page under the sheet is not re-rendered from the server,
 * keeps its state and its scroll, and the sheet opens without a round trip.
 * A link inside a panel navigates to a URL without `?panel`, which closes it.
 */
export function ShellProvider({ children }: { children: ReactNode }) {
  const raw = useSearchParams().get(PANEL_PARAM);
  const panel = isPanelId(raw) ? raw : null;
  const panelReturn = useRef<HTMLElement | null>(null);
  const paletteReturn = useRef<HTMLElement | null>(null);
  // The history entry this shell pushed for the open panel. Closing while
  // still on it steps back, so Back after a close does not land on a copy of
  // the same page.
  const pushed = useRef<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [title, setTitle] = useState<string | null>(null);

  const openPanel = useCallback(
    (id: PanelId, returnFocusTo?: HTMLElement | null) => {
      panelReturn.current =
        returnFocusTo === undefined ? activeElement() : returnFocusTo;
      preloadPanel(id);
      const url = urlWithPanel(id);
      const current = new URL(window.location.href).searchParams.get(
        PANEL_PARAM,
      );
      if (isPanelId(current)) {
        // Switching panels replaces the entry: one Back closes the sheet.
        window.history.replaceState(null, "", url);
        if (pushed.current) pushed.current = url;
      } else {
        window.history.pushState(null, "", url);
        pushed.current = url;
      }
    },
    [],
  );

  const closePanel = useCallback(() => {
    const onPushed = pushed.current !== null && pushed.current === here();
    pushed.current = null;
    if (onPushed) {
      window.history.back();
    } else {
      window.history.replaceState(null, "", urlWithPanel(null));
    }
  }, []);

  const openPalette = useCallback((returnFocusTo?: HTMLElement | null) => {
    paletteReturn.current =
      returnFocusTo === undefined ? activeElement() : returnFocusTo;
    setPaletteOpen(true);
  }, []);

  const value = useMemo<ShellContextValue>(
    () => ({
      panel,
      openPanel,
      closePanel,
      panelReturnFocus: () => panelReturn.current,
      paletteOpen,
      openPalette,
      setPaletteOpen,
      paletteReturnFocus: () => paletteReturn.current,
      title,
      setTitle,
    }),
    [panel, openPanel, closePanel, paletteOpen, openPalette, title],
  );

  return (
    <ShellContext.Provider value={value}>{children}</ShellContext.Provider>
  );
}

export function useShell(): ShellContextValue {
  const value = useContext(ShellContext);
  if (!value) throw new Error("useShell must be used within a ShellProvider");
  return value;
}

/**
 * A page's title in the top bar while the page is mounted (a thread names
 * itself). Null or empty leaves the path's own title.
 */
export function useShellTitle(title: string | null | undefined) {
  const { setTitle } = useShell();
  useEffect(() => {
    setTitle(title?.trim() ? title : null);
    return () => setTitle(null);
  }, [setTitle, title]);
}
