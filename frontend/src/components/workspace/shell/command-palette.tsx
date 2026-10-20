"use client";

import {
  BotIcon,
  HomeIcon,
  KeyboardIcon,
  MessageSquarePlusIcon,
  MonitorIcon,
  MoonIcon,
  PlugIcon,
  SettingsIcon,
  SunIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useI18n } from "@/core/i18n/hooks";
import { saveAppearance, type Appearance } from "@/core/preferences";
import { useGlobalShortcuts } from "@/hooks/use-global-shortcuts";

import { PaletteResults, matches } from "./palette-results";
import { PANEL_ICONS, PANEL_IDS, panelLabel, type PanelId } from "./panels";
import { useShell } from "./shell-context";

/** Save the theme on the server too (Settings > Appearance's store). A
 * gateway without the route (404) or offline leaves the local choice. */
function saveTheme(theme: Appearance) {
  void saveAppearance(theme).catch(() => undefined);
}

interface Action {
  id: string;
  label: string;
  icon: typeof BotIcon;
  shortcut?: string;
  run: () => void;
}

/**
 * ⌘K / Ctrl+K from anywhere, "/" when focus is not in a text field. Searches
 * chats, projects, tasks, agents, skills and automations, and runs commands.
 */
export function CommandPalette() {
  const { t } = useI18n();
  const router = useRouter();
  const { setTheme } = useTheme();
  const {
    paletteOpen,
    setPaletteOpen,
    openPalette,
    openPanel,
    paletteReturnFocus,
  } = useShell();
  const [query, setQuery] = useState("");
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [isMac, setIsMac] = useState(false);
  // Set when a command opens something else that takes focus (a panel), so
  // the palette does not pull focus back as it closes.
  const [handedOff, setHandedOff] = useState(false);

  useEffect(() => {
    setIsMac(navigator.userAgent.includes("Mac"));
  }, []);
  useEffect(() => {
    if (!paletteOpen) setQuery("");
  }, [paletteOpen]);

  const close = useCallback(() => setPaletteOpen(false), [setPaletteOpen]);

  const go = useCallback(
    (href: string) => {
      close();
      router.push(href);
    },
    [close, router],
  );

  const handleNewChat = useCallback(() => go("/workspace/chats/new"), [go]);
  const handleOpenSettings = useCallback(() => go("/workspace/settings"), [go]);
  const handleShowShortcuts = useCallback(() => {
    close();
    setShortcutsOpen(true);
  }, [close]);

  const applyTheme = useCallback(
    (theme: Appearance) => {
      setTheme(theme);
      saveTheme(theme);
      close();
    },
    [close, setTheme],
  );

  const openPanelFromPalette = useCallback(
    (id: PanelId) => {
      setHandedOff(true);
      const returnTo = paletteReturnFocus();
      close();
      openPanel(id, returnTo);
    },
    [close, openPanel, paletteReturnFocus],
  );

  const shortcuts = useMemo(
    () => [
      {
        key: "k",
        meta: true,
        action: () => (paletteOpen ? close() : openPalette()),
      },
      { key: "/", meta: false, action: () => openPalette() },
      { key: "n", meta: true, shift: true, action: handleNewChat },
      { key: ",", meta: true, action: handleOpenSettings },
      { key: "/", meta: true, action: handleShowShortcuts },
    ],
    [
      paletteOpen,
      close,
      openPalette,
      handleNewChat,
      handleOpenSettings,
      handleShowShortcuts,
    ],
  );
  useGlobalShortcuts(shortcuts);

  const metaKey = isMac ? "⌘" : "Ctrl+";
  const shiftKey = isMac ? "⇧" : "Shift+";

  const actions: Action[] = [
    {
      id: "new-chat",
      label: t.shell.newChat,
      icon: MessageSquarePlusIcon,
      shortcut: `${metaKey}${shiftKey}N`,
      run: handleNewChat,
    },
    {
      id: "new-agent",
      label: t.shell.newAgent,
      icon: BotIcon,
      run: () => go("/workspace/agents/new"),
    },
    {
      id: "connect-slack",
      label: t.shell.connectSlack,
      icon: PlugIcon,
      run: () => go("/workspace/connections"),
    },
    {
      id: "home",
      label: t.sidebar.home,
      icon: HomeIcon,
      run: () => go("/workspace/home"),
    },
    {
      id: "theme-dark",
      label: t.shell.darkTheme,
      icon: MoonIcon,
      run: () => applyTheme("dark"),
    },
    {
      id: "theme-light",
      label: t.shell.lightTheme,
      icon: SunIcon,
      run: () => applyTheme("light"),
    },
    {
      id: "theme-system",
      label: t.shell.systemTheme,
      icon: MonitorIcon,
      run: () => applyTheme("system"),
    },
    {
      id: "settings",
      label: t.shell.openSettings,
      icon: SettingsIcon,
      shortcut: `${metaKey},`,
      run: handleOpenSettings,
    },
    {
      id: "shortcuts",
      label: t.shell.keyboardShortcuts,
      icon: KeyboardIcon,
      shortcut: `${metaKey}/`,
      run: handleShowShortcuts,
    },
  ];
  const panelActions = PANEL_IDS.map((id) => ({
    id,
    label: t.shell.openPanel(panelLabel(t, id)),
    icon: PANEL_ICONS[id],
  }));

  const shownActions = actions.filter((a) => matches(query, a.label));
  const shownPanels = panelActions.filter((p) => matches(query, p.label));

  return (
    <>
      <Dialog open={paletteOpen} onOpenChange={setPaletteOpen}>
        <DialogContent
          className="overflow-hidden p-0"
          data-testid="command-palette"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            if (handedOff) {
              setHandedOff(false);
              return;
            }
            const target = paletteReturnFocus();
            if (target?.isConnected) target.focus();
          }}
        >
          <DialogTitle className="sr-only">{t.shell.paletteTitle}</DialogTitle>
          <DialogDescription className="sr-only">
            {t.shell.paletteDescription}
          </DialogDescription>
          <Command
            shouldFilter={false}
            label={t.shell.paletteTitle}
            className="[&_[cmdk-group-heading]]:text-muted-foreground **:data-[slot=command-input-wrapper]:h-12 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group]]:px-2 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:min-h-11 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-2"
          >
            <CommandInput
              placeholder={t.shell.palettePlaceholder}
              aria-label={t.shell.palettePlaceholder}
              value={query}
              onValueChange={setQuery}
            />
            <CommandList className="max-h-[min(420px,60vh)]">
              <CommandEmpty>{t.shell.noResults}</CommandEmpty>
              {query.trim() !== "" && (
                <PaletteResults query={query} onGo={go} />
              )}
              {shownPanels.length > 0 && (
                <CommandGroup heading={t.shell.groupPanels}>
                  {shownPanels.map(({ id, label, icon: Icon }) => (
                    <CommandItem
                      key={id}
                      value={`panel:${id}`}
                      onSelect={() => openPanelFromPalette(id)}
                    >
                      <Icon />
                      {label}
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}
              {shownActions.length > 0 && (
                <CommandGroup heading={t.shell.groupActions}>
                  {shownActions.map(
                    ({ id, label, icon: Icon, shortcut, run }) => (
                      <CommandItem
                        key={id}
                        value={`action:${id}`}
                        onSelect={run}
                      >
                        <Icon />
                        {label}
                        {shortcut && (
                          <CommandShortcut>{shortcut}</CommandShortcut>
                        )}
                      </CommandItem>
                    ),
                  )}
                </CommandGroup>
              )}
            </CommandList>
          </Command>
        </DialogContent>
      </Dialog>

      <Dialog open={shortcutsOpen} onOpenChange={setShortcutsOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t.shortcuts.keyboardShortcuts}</DialogTitle>
            <DialogDescription>
              {t.shortcuts.keyboardShortcutsDescription}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            {[
              { keys: `${metaKey}K`, label: t.shortcuts.openCommandPalette },
              { keys: "/", label: t.shortcuts.openCommandPalette },
              { keys: `${metaKey}${shiftKey}N`, label: t.sidebar.newChat },
              { keys: `${metaKey}B`, label: t.shortcuts.toggleSidebar },
              { keys: `${metaKey},`, label: t.common.settings },
              {
                keys: `${metaKey}/`,
                label: t.shortcuts.keyboardShortcuts,
              },
            ].map(({ keys, label }) => (
              <div key={keys} className="flex items-center justify-between">
                <span className="text-muted-foreground">{label}</span>
                <kbd className="bg-muted text-muted-foreground rounded px-2 py-0.5 font-mono text-xs">
                  {keys}
                </kbd>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
