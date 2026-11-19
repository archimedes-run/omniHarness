"use client";

import { useEffect } from "react";

import { documentLoadTarget } from "@/core/security/document-navigation";

/** Cover shared navigation (including portals) before Next Link handles a click. */
export function DocumentNavigation() {
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const anchor =
        event.target instanceof Element
          ? event.target.closest("a[href]")
          : null;
      const destination = documentLoadTarget(
        event,
        anchor instanceof HTMLAnchorElement
          ? {
              href: anchor.href,
              target: anchor.target,
              download: anchor.hasAttribute("download"),
            }
          : null,
        window.location.href,
      );
      if (!destination) return;
      event.preventDefault();
      event.stopPropagation();
      window.location.assign(destination);
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);
  return null;
}
