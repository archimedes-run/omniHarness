/**
 * Spec 012 Slice 2: at most ONE live inline artifact frame at a time. A chat
 * with N code cards runs one program, not N: a card asks for the slot while
 * it is on screen; the newest visible card holds it; a card that scrolls
 * away or unmounts gives it back (its frame is removed: paused, not
 * hidden). Opened views (the panel, the full page) do not use the slot.
 */

type Listener = (holder: string | null) => void;

let holder: string | null = null;
/** Cards on screen, oldest first: the slot falls back to the newest one left. */
let visible: string[] = [];
const listeners = new Set<Listener>();

function emit() {
  for (const l of listeners) l(holder);
}

export function liveSlotHolder(): string | null {
  return holder;
}

export function subscribeLiveSlot(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The card `key` is on screen (true) or not (false). */
export function setCardVisible(key: string, on: boolean): void {
  visible = visible.filter((k) => k !== key);
  if (on) visible.push(key);
  const next = visible.length ? visible[visible.length - 1]! : null;
  if (next !== holder) {
    holder = next;
    emit();
  }
}

/** Tests only. */
export function resetLiveSlot(): void {
  holder = null;
  visible = [];
  emit();
}
