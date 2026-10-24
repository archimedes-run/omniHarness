"use client";

import { useEffect, useRef } from "react";

/**
 * The CSS variable that holds the chat composer's height, in px. The message
 * list reads it for the clear space under its last message, so the composer
 * (which floats over the bottom of the thread) never covers it.
 */
export const COMPOSER_INSET_VAR = "--composer-inset";

/**
 * Keeps `--composer-inset` on `host` equal to the measured height of
 * `composer`: when its chips wrap onto a second line, the textarea grows, or
 * anything else in it changes size. A ResizeObserver, never a fixed number.
 */
export function useComposerInset<
  H extends HTMLElement = HTMLElement,
  C extends HTMLElement = HTMLDivElement,
>() {
  const hostRef = useRef<H>(null);
  const composerRef = useRef<C>(null);

  useEffect(() => {
    const host = hostRef.current;
    const composer = composerRef.current;
    if (!host || !composer) return;
    const update = () => {
      host.style.setProperty(
        COMPOSER_INSET_VAR,
        `${Math.ceil(composer.getBoundingClientRect().height)}px`,
      );
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(composer);
    return () => {
      observer.disconnect();
      host.style.removeProperty(COMPOSER_INSET_VAR);
    };
  }, []);

  return { hostRef, composerRef };
}
