"use client";

import {
  useMemo,
  type AnchorHTMLAttributes,
  type ComponentProps,
  type ComponentType,
} from "react";
import {
  Streamdown,
  defaultComponents,
  defaultRehypePlugins,
  type Components,
} from "streamdown";

import { ExternalLink } from "@/components/workspace/citations/external-link";
import { rehypeContentUrlGuard } from "@/core/streamdown/content-url-guard";
import { useMarkdownPlugins } from "@/core/streamdown/lazy-plugins";

export type MarkdownProps = ComponentProps<typeof Streamdown>;

type Anchor = ComponentType<AnchorHTMLAttributes<HTMLAnchorElement>>;

/**
 * Streamdown, with code highlighting and math loaded only when the text needs
 * them (core/streamdown/lazy-plugins.ts). Every markdown renderer in the app
 * goes through this, so no page pays for shiki or katex up front.
 *
 * It is also the zero-click exfiltration boundary: every renderer's last
 * rehype step is the content URL guard (core/streamdown/content-url-guard.ts),
 * so an image from another origin is never fetched, and a link to another
 * origin is a button that shows its URL before anything is opened.
 */
export function Markdown({
  children,
  plugins,
  rehypePlugins,
  components,
  ...props
}: MarkdownProps) {
  const lazy = useMarkdownPlugins(
    typeof children === "string" ? children : undefined,
  );
  // Streamdown's own defaults (raw, sanitize, harden) apply only when no
  // plugins are passed; passing the guard alone would drop them.
  const guarded = useMemo(
    () => [
      ...(rehypePlugins ?? Object.values(defaultRehypePlugins)),
      rehypeContentUrlGuard,
    ],
    [rehypePlugins],
  );
  const guardedComponents = useMemo((): Components => {
    const Inner = (components?.a ?? defaultComponents.a) as Anchor;
    function GuardedAnchor(props: AnchorHTMLAttributes<HTMLAnchorElement>) {
      const external = (props as Record<string, unknown>)["data-external-href"];
      if (typeof external === "string") {
        return (
          <ExternalLink href={external} className={props.className}>
            {props.children}
          </ExternalLink>
        );
      }
      return <Inner {...props} />;
    }
    return { ...components, a: GuardedAnchor } as Components;
  }, [components]);
  return (
    <Streamdown
      plugins={{ ...lazy, ...plugins }}
      rehypePlugins={guarded}
      components={guardedComponents}
      {...props}
    >
      {children}
    </Streamdown>
  );
}
