/**
 * Long pasted text travels inside the message as a `<pasted_text>` block, so
 * the model reads it exactly as if it had been typed, while the composer and
 * the chat show it as a small card that opens on demand.
 */

const OPEN = "<pasted_text>";
const CLOSE = "</pasted_text>";

/** A paste at least this long, or with at least this many lines, becomes a card. */
export const PASTE_MIN_CHARS = 1500;
export const PASTE_MIN_LINES = 25;

const BLOCK = /<pasted_text>\n?([\s\S]*?)\n?<\/pasted_text>/g;

export function shouldCollapsePaste(text: string): boolean {
  // Text that itself contains the markers could not be told apart from the
  // wrapper later, so it is left as an ordinary paste.
  if (text.includes(OPEN) || text.includes(CLOSE)) {
    return false;
  }
  if (text.length >= PASTE_MIN_CHARS) {
    return true;
  }
  return text.split("\n").length >= PASTE_MIN_LINES;
}

/** The message text to send: what was typed, then each pasted block. */
export function wrapPastes(typed: string, pastes: readonly string[]): string {
  const blocks = pastes.map((p) => `${OPEN}\n${p}\n${CLOSE}`);
  return [typed.trim(), ...blocks]
    .filter((part) => part.length > 0)
    .join("\n\n");
}

/** Splits a stored message into its typed text and its pasted blocks. */
export function splitPastedText(content: string): {
  text: string;
  pastes: string[];
} {
  if (!content.includes(OPEN)) {
    return { text: content, pastes: [] };
  }
  const pastes: string[] = [];
  const text = content
    .replace(BLOCK, (_match, body: string) => {
      pastes.push(body);
      return "";
    })
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return { text, pastes };
}

/** The first words of a paste, on one line, to label its card. */
export function pastePreview(text: string, max = 140): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max).trimEnd()}…` : flat;
}

/** "1,204 words · 38 lines" */
export function pasteSize(text: string): string {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  const lines = text.split("\n").length;
  return `${words.toLocaleString("en-US")} ${words === 1 ? "word" : "words"} · ${lines.toLocaleString("en-US")} ${lines === 1 ? "line" : "lines"}`;
}

/** A typed message longer than this is shown folded, with "Show more". */
export const LONG_MESSAGE_CHARS = 600;
export const LONG_MESSAGE_PARAGRAPHS = 2;

export function isLongMessage(text: string): boolean {
  if (text.length > LONG_MESSAGE_CHARS) {
    return true;
  }
  const paragraphs = text.split(/\n\s*\n/).filter((p) => p.trim().length > 0);
  return paragraphs.length > LONG_MESSAGE_PARAGRAPHS;
}
