"use client";

import { Fragment, type ReactNode } from "react";

/**
 * A small preview of a skill's instructions: headings, bullets, bold, italic
 * and inline code. Deliberately not the chat's markdown renderer, which pulls
 * a highlighter and math into the panel (bundle-budget.spec.ts). Text only:
 * nothing is injected as HTML.
 */
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*|_[^_]+_)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const token = m[0];
    if (token.startsWith("**")) {
      out.push(
        <strong key={i++} className="font-semibold">
          {token.slice(2, -2)}
        </strong>,
      );
    } else if (token.startsWith("`")) {
      out.push(
        <code key={i++} className="bg-surface-raised rounded px-1 font-mono">
          {token.slice(1, -1)}
        </code>,
      );
    } else {
      out.push(<em key={i++}>{token.slice(1, -1)}</em>);
    }
    last = m.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function MarkdownLite({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  return (
    <>
      {lines.map((line, index) => {
        const heading = /^(#{1,6})\s+(.*)$/.exec(line);
        if (heading) {
          return (
            <div key={index} className="text-base font-semibold">
              {inline(heading[2] ?? "")}
            </div>
          );
        }
        const bullet = /^\s*(?:[-*+]|\d+\.)\s+(.*)$/.exec(line);
        if (bullet) {
          return (
            <div key={index} className="pl-4">
              {"• "}
              {inline(bullet[1] ?? "")}
            </div>
          );
        }
        if (!line.trim()) return <Fragment key={index} />;
        return <div key={index}>{inline(line)}</div>;
      })}
    </>
  );
}
