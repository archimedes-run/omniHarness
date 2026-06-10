"use client";

import { cn } from "@/lib/utils";

export function OmniBrandMark({
  className,
  animated = false,
  size = "md",
}: {
  className?: string;
  animated?: boolean;
  size?: "sm" | "md" | "lg";
}) {
  const sizeClass =
    size === "sm" ? "size-7" : size === "lg" ? "size-10" : "size-8";
  const textClass =
    size === "sm"
      ? "text-[1.35rem]"
      : size === "lg"
        ? "text-[2rem]"
        : "text-[1.7rem]";

  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex shrink-0 items-center justify-center font-semibold text-black select-none",
        sizeClass,
        textClass,
        animated && "transition-transform duration-300 ease-out",
        className,
      )}
    >
      O
    </span>
  );
}
