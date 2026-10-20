"use client";

import type { ComponentProps } from "react";
import { Streamdown } from "streamdown";

import { useMarkdownPlugins } from "@/core/streamdown/lazy-plugins";

export type MarkdownProps = ComponentProps<typeof Streamdown>;

/**
 * Streamdown, with code highlighting and math loaded only when the text needs
 * them (core/streamdown/lazy-plugins.ts). Every markdown renderer in the app
 * goes through this, so no page pays for shiki or katex up front.
 */
export function Markdown({ children, plugins, ...props }: MarkdownProps) {
  const lazy = useMarkdownPlugins(
    typeof children === "string" ? children : undefined,
  );
  return (
    <Streamdown plugins={{ ...lazy, ...plugins }} {...props}>
      {children}
    </Streamdown>
  );
}
