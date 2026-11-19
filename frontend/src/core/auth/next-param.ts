/** The landing page used when the login return path is missing or rejected. */
export const DEFAULT_LOGIN_LANDING = "/workspace";

// Backslashes are treated as slashes by URL parsers; control characters are
// stripped by them. Either can turn a path into a different host.
const UNSAFE_CHARACTERS = /[\\\u0000-\u001f\u007f]/;

/**
 * Validate the login `next` parameter: only a same-origin path is accepted.
 * Returns the normalised path, or null when the value must not be used.
 */
export function validateNextParam(
  next: string | null,
  origin: string,
): string | null {
  if (!next) return null;
  if (!next.startsWith("/") || next.startsWith("//")) return null;
  if (UNSAFE_CHARACTERS.test(next)) return null;
  let url: URL;
  try {
    url = new URL(next, origin);
  } catch {
    return null;
  }
  if (url.origin !== new URL(origin).origin) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}
