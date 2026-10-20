"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * A stated plan, readable: the small markdown the policy layer writes
 * (**bold**, `code`, "- " items, paragraphs), turned into React elements.
 *
 * NEVER HTML. The plan can carry text that came from content (a page, an
 * email), so nothing in it is parsed as markup: every piece is a React text
 * node, which React escapes. A full markdown renderer with raw HTML on
 * (the chat's) is deliberately not used here.
 *
 * A long line (a dumped argument list) is cut, with "Show all".
 */
export const CUT_AT = 140;

function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return (
        <strong key={index} className="font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code
          key={index}
          className="bg-muted rounded px-1 font-mono text-[0.92em]"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}

/** A line, cut at CUT_AT characters with a toggle to show it whole. */
export function LongText({
  text,
  cutAt = CUT_AT,
}: {
  text: string;
  cutAt?: number;
}) {
  const [open, setOpen] = useState(false);
  if (text.length <= cutAt) return <>{inline(text)}</>;
  return (
    <>
      {open ? inline(text) : inline(`${text.slice(0, cutAt).trimEnd()}…`)}{" "}
      <Button
        type="button"
        variant="link"
        size="sm"
        className="h-auto p-0 align-baseline text-xs"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        data-testid="show-all"
      >
        {open ? "Show less" : "Show all"}
      </Button>
    </>
  );
}

type Block = { kind: "p"; lines: string[] } | { kind: "ul"; items: string[] };

function blocks(text: string): Block[] {
  const out: Block[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const item = /^\s*[-*]\s+(.*)$/.exec(line);
    const last = out[out.length - 1];
    if (item) {
      if (last?.kind === "ul") last.items.push(item[1]!);
      else out.push({ kind: "ul", items: [item[1]!] });
    } else if (!line.trim()) {
      out.push({ kind: "p", lines: [] });
    } else if (last?.kind === "p") {
      last.lines.push(line.trim());
    } else {
      out.push({ kind: "p", lines: [line.trim()] });
    }
  }
  return out.filter((b) => (b.kind === "p" ? b.lines.length > 0 : true));
}

export function PlanText({ text }: { text: string }) {
  return (
    <div className="text-foreground space-y-2 text-sm" data-testid="plan-text">
      {blocks(text).map((block, index) =>
        block.kind === "ul" ? (
          <ul key={index} className="list-disc space-y-1 pl-5">
            {block.items.map((item, i) => (
              <li key={i} className="break-words">
                <LongText text={item} />
              </li>
            ))}
          </ul>
        ) : (
          <p key={index} className="break-words">
            {block.lines.map((line, i) => (
              <span key={i}>
                {i > 0 && <br />}
                <LongText text={line} />
              </span>
            ))}
          </p>
        ),
      )}
    </div>
  );
}

/** The call's arguments, one row each, long values cut with "Show all". */
export function ArgumentsSummary({ args }: { args: Record<string, string> }) {
  const entries = Object.entries(args);
  if (entries.length === 0) return null;
  return (
    <dl
      className="border-border grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-md border px-3 py-2 text-sm"
      data-testid="arguments"
    >
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-muted-foreground font-mono text-xs leading-5">
            {key}
          </dt>
          <dd className="min-w-0 break-words whitespace-pre-wrap">
            <LongText text={value} cutAt={120} />
          </dd>
        </div>
      ))}
    </dl>
  );
}
