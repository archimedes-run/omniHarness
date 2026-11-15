/**
 * Spec 012 FR-019: when an artifact frame may raise the host's "Open link?"
 * dialog. One dialog at a time; a pause after one closes; and only while the
 * frame holds the focus (the owner clicked into it), so a link the artifact
 * clicks for itself, with the owner elsewhere, raises nothing.
 */
export const LINK_COOLDOWN_MS = 3000;

export class LinkGate {
  private open = false;
  private closedAt = -Infinity;

  request(
    _url: string,
    frameHasFocus: boolean,
    now: number,
  ): { ok: true } | { ok: false; reason: string } {
    if (this.open) return { ok: false, reason: "open_busy" };
    if (now - this.closedAt < LINK_COOLDOWN_MS)
      return { ok: false, reason: "open_too_soon" };
    if (!frameHasFocus) return { ok: false, reason: "open_without_click" };
    this.open = true;
    return { ok: true };
  }

  closed(now: number): void {
    if (this.open) this.closedAt = now;
    this.open = false;
  }
}

/** The address (scheme, host, path) and the rest (query and fragment),
 * which the dialog highlights: that part is what the site receives. */
export function splitLink(raw: string): { base: string; rest: string } {
  const url = new URL(raw);
  return {
    base: `${url.protocol}//${url.host}${url.pathname}`,
    rest: `${url.search}${url.hash}`,
  };
}
