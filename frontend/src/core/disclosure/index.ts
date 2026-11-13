/**
 * The policy layer's Tier 2 disclosure, shown as a system note (spec 009
 * Slice 0). When the assistant's reply does not mention an action that ran
 * without a confirmation, the policy layer appends "Also, for the record: ..."
 * to the reply's text and marks the appended block on the message
 * (`additional_kwargs.omniharness_disclosure`). The chat shows that block under
 * the answer as a compact note from the system, instead of as the assistant
 * narrating its own tool calls. The text itself is unchanged (other channels,
 * history and copying still carry it), and only a block the server marked is
 * moved: nothing in the reply is matched by wording.
 */

export const DISCLOSURE_MARKER = "omniharness_disclosure";

export interface DisclosureItem {
  tool: string;
  text: string;
}

export interface SplitDisclosure {
  body: string;
  items: DisclosureItem[];
}

function asItems(value: unknown): DisclosureItem[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const { tool, text } = item as Record<string, unknown>;
    return typeof tool === "string" && tool
      ? [{ tool, text: typeof text === "string" ? text : "" }]
      : [];
  });
}

/**
 * The reply without the marked disclosure block, and the block's items. A
 * marker whose block is not at the end of the text (edited, or stale) is
 * ignored and the text is shown whole.
 */
export function splitDisclosure(
  content: string,
  additionalKwargs: Record<string, unknown> | undefined,
): SplitDisclosure {
  const marker = additionalKwargs?.[DISCLOSURE_MARKER];
  if (!marker || typeof marker !== "object")
    return { body: content, items: [] };
  const { text, items } = marker as Record<string, unknown>;
  const parsed = asItems(items);
  if (typeof text !== "string" || !text || !parsed.length) {
    return { body: content, items: [] };
  }
  if (!content.endsWith(text)) return { body: content, items: [] };
  return {
    body: content.slice(0, content.length - text.length).trimEnd(),
    items: parsed,
  };
}

/**
 * Every action of the reply on ONE line, in the order each tool first ran,
 * repeats counted: "code_job, ledger_apply ×2" (owner decision, PR #174).
 */
export function disclosureSummary(items: DisclosureItem[]): string {
  const counts = new Map<string, number>();
  for (const item of items)
    counts.set(item.tool, (counts.get(item.tool) ?? 0) + 1);
  return [...counts]
    .map(([tool, n]) => (n > 1 ? `${tool} \u00d7${n}` : tool))
    .join(", ");
}
