"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { XIcon } from "lucide-react";
import {
  Component,
  Suspense,
  lazy,
  useEffect,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";

import { DialogOverlay, DialogPortal } from "@/components/ui/dialog";
import { useI18n } from "@/core/i18n/hooks";

import {
  PANEL_ICONS,
  PANEL_LOADERS,
  panelLabel,
  type PanelId,
  type PanelProps,
} from "./panels";
import { useShell } from "./shell-context";

const CONTENT: Record<PanelId, ComponentType<PanelProps>> = {
  agents: lazy(PANEL_LOADERS.agents),
  skills: lazy(PANEL_LOADERS.skills),
  automations: lazy(PANEL_LOADERS.automations),
  tasks: lazy(PANEL_LOADERS.tasks),
};

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

  const Icon = PANEL_ICONS[id];
  const Content = CONTENT[id];
  const label = panelLabel(t, id);

  return (
    <DialogPrimitive.Root
      open={panel !== null}
      onOpenChange={(open) => {
        if (!open) closePanel();
      }}
    >
      <DialogPortal>
        <DialogOverlay className="duration-100" />
        <DialogPrimitive.Content
          data-testid="panel-sheet"
          data-panel={id}
          aria-describedby={undefined}
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
          className="bg-background text-foreground border-border data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 fixed inset-0 z-50 mx-auto flex max-w-[1240px] flex-col overflow-hidden duration-100 outline-none sm:inset-4 sm:rounded-xl sm:border sm:shadow-lg md:inset-6"
        >
          <div className="border-border flex shrink-0 items-center gap-3 border-b px-4 py-2 sm:px-5">
            <Icon className="text-muted-foreground size-4" aria-hidden />
            <DialogPrimitive.Title className="flex-1 text-[15px] font-semibold">
              {label}
            </DialogPrimitive.Title>
            <DialogPrimitive.Close
              className="text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-ring flex size-11 items-center justify-center rounded-md outline-none focus-visible:ring-2 md:size-9"
              aria-label={t.shell.close}
              data-testid="panel-close"
            >
              <XIcon className="size-4" />
            </DialogPrimitive.Close>
          </div>
          <div
            className="min-h-0 flex-1 overflow-y-auto"
            data-testid="panel-body"
          >
            <PanelBoundary
              key={id}
              fallback={
                <p
                  className="text-destructive p-6 text-sm"
                  role="alert"
                  data-testid="panel-failed"
                >
                  {t.shell.panelFailed}
                </p>
              }
            >
              <Suspense
                fallback={
                  <p
                    className="text-muted-foreground p-6 text-sm"
                    data-testid="panel-loading"
                  >
                    {t.shell.loadingPanel}
                  </p>
                }
              >
                <Content onClose={closePanel} />
              </Suspense>
            </PanelBoundary>
          </div>
        </DialogPrimitive.Content>
      </DialogPortal>
    </DialogPrimitive.Root>
  );
}
