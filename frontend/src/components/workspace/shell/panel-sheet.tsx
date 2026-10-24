"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { XIcon } from "lucide-react";
import {
  Component,
  createElement,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";

import { DialogOverlay, DialogPortal } from "@/components/ui/dialog";
import { useI18n } from "@/core/i18n/hooks";

import {
  PANEL_ICONS,
  PANEL_LOADERS,
  SELF_CHROME_PANELS,
  panelLabel,
  type CloseGuard,
  type PanelId,
  type PanelProps,
} from "./panels";
import { useShell } from "./shell-context";

type Loaded = ComponentType<PanelProps> | "failed";
const LOADED: Partial<Record<PanelId, Loaded>> = {};

/**
 * The panel's component once its code has arrived. Not React.lazy: React 19
 * holds a Suspense fallback on screen for at least 300 ms, which made every
 * first open take 300 ms however fast the chunk came.
 */
function usePanelComponent(id: PanelId): Loaded | null {
  const [, rerender] = useState(0);
  useEffect(() => {
    if (LOADED[id]) return;
    let live = true;
    PANEL_LOADERS[id]()
      .then((m) => {
        LOADED[id] = m.default;
      })
      .catch(() => {
        LOADED[id] = "failed";
      })
      .finally(() => {
        if (live) rerender((n) => n + 1);
      });
    return () => {
      live = false;
    };
  }, [id]);
  return LOADED[id] ?? null;
}

/** A panel whose code failed to load says so: an empty sheet would read as
 * "nothing here". */
class PanelBoundary extends Component<
  { fallback: ReactNode; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/**
 * The capsule's panel, as a large sheet over the current page. Dialog
 * semantics from Radix (focus trap, Esc closes); focus goes back to whatever
 * opened it (the capsule button, or what was focused before the palette).
 */
export function PanelSheet() {
  const { t } = useI18n();
  const { panel, closePanel, panelReturnFocus } = useShell();
  // Keep the last panel through the close so the sheet does not go blank
  // while it leaves.
  const [shown, setShown] = useState<PanelId | null>(panel);
  useEffect(() => {
    if (panel) setShown(panel);
  }, [panel]);
  const id = panel ?? shown;
  if (!id) return null;
  return (
    <SheetFor
      id={id}
      open={panel !== null}
      closePanel={closePanel}
      panelReturnFocus={panelReturnFocus}
      t={t}
    />
  );
}

function SheetFor({
  id,
  open,
  closePanel,
  panelReturnFocus,
  t,
}: {
  id: PanelId;
  open: boolean;
  closePanel: () => void;
  panelReturnFocus: () => HTMLElement | null;
  t: ReturnType<typeof useI18n>["t"];
}) {
  const Icon = PANEL_ICONS[id];
  const Content = usePanelComponent(id);
  const label = panelLabel(t, id);
  const selfChrome = SELF_CHROME_PANELS.has(id);
  // A panel with unsaved work answers first (see PanelProps.setCloseGuard).
  const guard = useRef<CloseGuard | null>(null);
  const setCloseGuard = useCallback((next: CloseGuard | null) => {
    guard.current = next;
  }, []);
  const guarded =
    (reason: "escape" | "outside") =>
    (event: { preventDefault: () => void }) => {
      if (guard.current?.(reason)) event.preventDefault();
    };
  const failed = (
    <p
      className="text-destructive p-6 text-sm"
      role="alert"
      data-testid="panel-failed"
    >
      {t.shell.panelFailed}
    </p>
  );

  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(open) => {
        if (!open) closePanel();
      }}
    >
      <DialogPortal>
        {/* From md up the top bar stays in view above the scrim, so the
            capsule shows which panel is open (Chat-Bar-v2.dc.html). */}
        <DialogOverlay className="duration-100 md:top-16" />
        <DialogPrimitive.Content
          data-testid="panel-sheet"
          data-panel={id}
          aria-describedby={undefined}
          onEscapeKeyDown={guarded("escape")}
          onPointerDownOutside={guarded("outside")}
          onInteractOutside={guarded("outside")}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            const target =
              panelReturnFocus() ??
              document.querySelector<HTMLElement>(`[data-capsule="${id}"]`);
            if (target?.isConnected) target.focus();
            else
              document
                .querySelector<HTMLElement>(`[data-capsule="${id}"]`)
                ?.focus();
          }}
          className={
            selfChrome
              ? "bg-card text-foreground border-border data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 fixed inset-0 z-50 m-auto flex h-full w-full flex-col overflow-hidden duration-100 outline-none sm:h-[min(840px,calc(100dvh-48px))] sm:w-[min(1080px,calc(100vw-32px))] sm:rounded-[18px] sm:border sm:shadow-2xl md:top-16 md:h-[min(840px,calc(100dvh-88px))]"
              : "bg-background text-foreground border-border data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 fixed inset-0 z-50 mx-auto flex max-w-[1240px] flex-col overflow-hidden duration-100 outline-none sm:inset-4 sm:rounded-xl sm:border sm:shadow-lg md:inset-6 md:top-[72px]"
          }
        >
          {selfChrome ? (
            <DialogPrimitive.Title className="sr-only">
              {label}
            </DialogPrimitive.Title>
          ) : null}
          <div
            className="border-border flex shrink-0 items-center gap-3 border-b px-4 py-2 sm:px-5"
            hidden={selfChrome}
          >
            <Icon className="text-muted-foreground size-4" aria-hidden />
            {selfChrome ? null : (
              <DialogPrimitive.Title className="flex-1 text-[15px] font-semibold">
                {label}
              </DialogPrimitive.Title>
            )}
            <DialogPrimitive.Close
              className="text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-ring flex size-11 items-center justify-center rounded-md outline-none focus-visible:ring-2 md:size-9"
              aria-label={t.shell.close}
              data-testid={selfChrome ? undefined : "panel-close"}
            >
              <XIcon className="size-4" />
            </DialogPrimitive.Close>
          </div>
          <div
            className={
              selfChrome
                ? "flex min-h-0 flex-1 flex-col"
                : "min-h-0 flex-1 overflow-y-auto"
            }
            data-testid="panel-body"
          >
            {Content === "failed" ? (
              failed
            ) : Content ? (
              <PanelBoundary key={selfChrome ? "studio" : id} fallback={failed}>
                {/* The component comes from the module cache, the same one
                    on every render (not created here). */}
                {createElement(Content, {
                  onClose: closePanel,
                  panel: id,
                  setCloseGuard,
                })}
              </PanelBoundary>
            ) : (
              <p
                className="text-muted-foreground p-6 text-sm"
                data-testid="panel-loading"
              >
                {t.shell.loadingPanel}
              </p>
            )}
          </div>
        </DialogPrimitive.Content>
      </DialogPortal>
    </DialogPrimitive.Root>
  );
}
