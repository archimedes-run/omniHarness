/**
 * Which agent or skill a studio panel shows, as `?item=` beside `?panel=`, so
 * a copied panel URL opens on the same item. Written with replaceState, like
 * the panel param itself, and removed when the panel closes.
 */
export const ITEM_PARAM = "item";

export function readItemParam(): string | null {
  if (typeof window === "undefined") return null;
  return new URL(window.location.href).searchParams.get(ITEM_PARAM);
}

export function writeItemParam(value: string | null) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (value) url.searchParams.set(ITEM_PARAM, value);
  else url.searchParams.delete(ITEM_PARAM);
  const next = `${url.pathname}${url.search}${url.hash}`;
  const now = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== now) window.history.replaceState(window.history.state, "", next);
}
