/**
 * Pure rules behind the chat bar's chips (Chat-Bar-v2.dc.html), kept apart
 * from React so they are tested directly (tests/unit/chat-bar-chips.test.ts).
 */
import { mentionToken, type StatusWord, type Trigger } from "./logic";

/** Integration chips shown before "+N integrations". */
export const INTEGRATIONS_SHOWN = 4;

/**
 * A selected integration that is not working. Its chip says so (dashed warn
 * border and the word) and overflow never hides it.
 */
export function isUnhealthy(status: StatusWord): boolean {
  return (
    status === "Unreachable" || status === "Off" || status === "Not connected"
  );
}

/** Can't tell: said in words, never shown as working or as failing. */
export function isUnknown(status: StatusWord): boolean {
  return status === "Not checked yet" || status === "Status unknown";
}

/**
 * The chips a group shows. Collapsed, at most `shown` of them, but an item
 * `keep` holds on to is always shown (and counts toward the limit). Order is
 * kept either way.
 */
export function collapse<T>(
  items: readonly T[],
  shown: number,
  expanded: boolean,
  keep: (item: T) => boolean = () => false,
): { visible: T[]; hidden: number } {
  if (expanded) return { visible: [...items], hidden: 0 };
  const kept = items.filter(keep).length;
  let room = Math.max(0, shown - kept);
  const visible = items.filter((item) => {
    if (keep(item)) return true;
    if (room > 0) {
      room -= 1;
      return true;
    }
    return false;
  });
  return { visible, hidden: items.length - visible.length };
}

// ---- skills ------------------------------------------------------------------

/**
 * The chat's removed-skills list after the picker's switch: off adds the
 * skill, on takes it out again.
 */
export function withSkill(
  excluded: readonly string[],
  name: string,
  on: boolean,
): string[] {
  const next = new Set(excluded);
  if (on) next.delete(name);
  else next.add(name);
  return [...next].sort();
}

// ---- keyboard ----------------------------------------------------------------

export type ChipKeyResult =
  | { kind: "focus"; index: number }
  | { kind: "remove"; index: number; focusAfter: number | "textarea" }
  | { kind: "textarea" }
  | null;

/**
 * A key on a focused chip: arrows move between chips (past the last one,
 * back to the message), Delete or Backspace removes a removable chip and
 * focus goes to its neighbour, Esc returns to the message.
 */
export function chipKey(
  key: string,
  index: number,
  chips: readonly { removable: boolean }[],
): ChipKeyResult {
  const last = chips.length - 1;
  switch (key) {
    case "ArrowLeft":
    case "ArrowUp":
      return index > 0 ? { kind: "focus", index: index - 1 } : null;
    case "ArrowRight":
    case "ArrowDown":
      return index < last
        ? { kind: "focus", index: index + 1 }
        : { kind: "textarea" };
    case "Home":
      return { kind: "focus", index: 0 };
    case "End":
      return { kind: "focus", index: last };
    case "Escape":
      return { kind: "textarea" };
    case "Delete":
    case "Backspace": {
      if (!chips[index]?.removable) return null;
      if (last === 0) return { kind: "remove", index, focusAfter: "textarea" };
      // The list is one shorter afterwards: Backspace goes back a chip,
      // Delete stays put (now on the next one), or back at the end.
      const focusAfter =
        key === "Backspace"
          ? Math.max(0, index - 1)
          : Math.min(index, last - 1);
      return { kind: "remove", index, focusAfter };
    }
    default:
      return null;
  }
}

/** Backspace in an empty message goes to the chips, starting at the last. */
export function backspaceToChips(value: string, chipCount: number): boolean {
  return value === "" && chipCount > 0;
}

// ---- mentions ----------------------------------------------------------------

/**
 * Picking an agent from the "@" menu: the typed "@que" becomes "@name ", the
 * text on both sides stays, and the caret lands right after the mention.
 */
export function insertMention(
  text: string,
  trigger: Pick<Trigger, "start">,
  caret: number,
  name: string,
): { text: string; caret: number } {
  const before = text.slice(0, trigger.start);
  const after = text.slice(caret).replace(/^ /, "");
  const token = `${mentionToken(name)} `;
  return { text: before + token + after, caret: before.length + token.length };
}
