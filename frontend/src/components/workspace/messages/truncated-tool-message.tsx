"use client";

import { cn } from "@/lib/utils";

const TRUNCATION_RE = /\[... TRUNCATED (\d+) chars \.\.\.\]\s*$/;

export function extractTruncationInfo(content: string): {
  cleanContent: string;
  truncatedChars: number | null;
} {
  const match = TRUNCATION_RE.exec(content);
  if (!match) return { cleanContent: content, truncatedChars: null };
  return {
    cleanContent: content.slice(0, match.index).trimEnd(),
    truncatedChars: parseInt(match[1], 10),
  };
}

export function TruncationBadge({
  truncatedChars,
  className,
}: {
  truncatedChars: number;
  className?: string;
}) {
  const kb = (truncatedChars / 1024).toFixed(1);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5",
        "bg-stone-800 text-stone-400 text-[10px] font-mono",
        className,
      )}
      title={`${truncatedChars.toLocaleString()} characters were removed to stay within the model context window`}
    >
      <span className="text-stone-500">[truncated</span>
      <span>{kb} KB</span>
      <span className="text-stone-500">removed]</span>
    </span>
  );
}
