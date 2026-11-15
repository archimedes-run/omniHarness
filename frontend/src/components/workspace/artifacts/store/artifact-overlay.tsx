"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import { tooltipEscapes } from "./viewer-parts";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Spec 012: the artifact panel full screen at phone width. A modal dialog:
 * focus moves in, Tab stays inside, Escape closes, and focus returns to
 * where it was.
 */
export function ArtifactOverlay({
  onClose,
  children,
}: {
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const el = ref.current;
    // The dialog itself takes focus (Tab then starts at its first control):
    // focusing the first control showed its tooltip over the title.
    el?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (!el) return;
      if (e.key === "Escape") {
        // A menu, popover, sheet or field inside handled it first.
        if (e.defaultPrevented && !tooltipEscapes.has(e)) return;
        e.preventDefault();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const head = items[0]!;
      const tail = items[items.length - 1]!;
      const active = document.activeElement;
      if (e.shiftKey && (active === head || !el.contains(active))) {
        e.preventDefault();
        tail.focus();
      } else if (!e.shiftKey && (active === tail || !el.contains(active))) {
        e.preventDefault();
        head.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      before?.focus?.();
    };
  }, []);
  return createPortal(
    <div
      ref={ref}
      tabIndex={-1}
      className="bg-background fixed inset-0 z-50 flex flex-col overflow-hidden outline-none"
      role="dialog"
      aria-modal="true"
      aria-label="Artifact"
      data-testid="artifact-panel-mobile"
    >
      {children}
    </div>,
    document.body,
  );
}
