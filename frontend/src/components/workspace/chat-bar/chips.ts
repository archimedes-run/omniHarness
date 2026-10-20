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

/**
 * What a file chip's preview says about a file that is not an image: its
 * name, its type and its size, each "unknown" in words when it cannot be told.
 */
export function fileFacts(f: {
  filename?: string;
  mediaType?: string;
  size?: number;
}): { name: string; type: string; size: string } {
  const name = f.filename?.trim() ? f.filename.trim() : "Attachment";
  const ext = /\.([a-z0-9]{1,8})$/i.exec(name)?.[1];
  // "application/octet-stream" is the browser's "no idea": not a type.
  const media = f.mediaType?.trim();
  const type =
    media && media !== "application/octet-stream"
      ? media
      : ext
        ? `${ext.toUpperCase()} file`
        : "Type unknown";
  return { name, type, size: formatBytes(f.size) };
}

/** 1,536 bytes reads "1.5 KB"; no size reads "Size unknown". */
export function formatBytes(bytes: number | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) {
    return "Size unknown";
  }
  if (bytes < 1024) return `${bytes} ${bytes === 1 ? "byte" : "bytes"}`;
  const units = ["KB", "MB", "GB", "TB"];
  let n = bytes / 1024;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n >= 10 ? Math.round(n) : Math.round(n * 10) / 10} ${units[i]}`;
}
