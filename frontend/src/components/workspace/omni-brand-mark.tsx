"use client";

import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * The OmniHarness mark: a ring with a node on its orbit (public/images/mark.svg,
 * src/app/icon.svg). Drawn in the current text colour, so it follows the theme
 * instead of being black on a dark sidebar.
 */
export function OmniBrandMark({
  className,
  animated = false,
  size = "md",
}: {
  className?: string;
  animated?: boolean;
  size?: "sm" | "md" | "lg";
}) {
  const cut = useId();
  const sizeClass =
    size === "sm" ? "size-6" : size === "lg" ? "size-9" : "size-7";
  return (
    <svg
      viewBox="0 0 100 100"
      aria-hidden="true"
      className={cn(
        "text-foreground shrink-0",
        sizeClass,
        animated && "transition-transform duration-300 ease-out",
        className,
      )}
    >
      <mask id={cut}>
        <rect width="100" height="100" fill="white" />
        <circle cx="72" cy="28" r="17" fill="black" />
      </mask>
      <circle
        cx="50"
        cy="50"
        r="31"
        fill="none"
        stroke="currentColor"
        strokeWidth="11"
        mask={`url(#${cut})`}
      />
      <circle cx="72" cy="28" r="11" fill="currentColor" />
    </svg>
  );
}
