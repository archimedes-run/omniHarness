import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import type { StreamdownProps } from "streamdown";

import { rehypeSplitWordsIntoSpans } from "../rehype";

export const streamdownPlugins = {
  remarkPlugins: [remarkGfm] as StreamdownProps["remarkPlugins"],
  rehypePlugins: [rehypeRaw] as StreamdownProps["rehypePlugins"],
};

export const streamdownPluginsWithWordAnimation = {
  remarkPlugins: [remarkGfm] as StreamdownProps["remarkPlugins"],
  rehypePlugins: [
    rehypeSplitWordsIntoSpans,
  ] as StreamdownProps["rehypePlugins"],
};

// Plugins for reasoning/thinking content — derived from streamdownPlugins but without rehypeRaw,
// to prevent LLM-hallucinated HTML tags (e.g. <simd>) from being rendered as DOM elements.
export const reasoningPlugins = {
  remarkPlugins: streamdownPlugins.remarkPlugins,
  rehypePlugins: streamdownPlugins.rehypePlugins?.filter(
    (p) => p !== rehypeRaw,
  ) as StreamdownProps["rehypePlugins"],
};

// Plugins for human messages - no autolink to prevent URL bleeding into adjacent text
export const humanMessagePlugins = {
  // No remark-gfm (no autolink literals). Math, when a message has any, comes
  // from the lazily loaded math plugin (core/streamdown/lazy-plugins.ts).
  remarkPlugins: [] as StreamdownProps["remarkPlugins"],
  rehypePlugins: [] as StreamdownProps["rehypePlugins"],
};
