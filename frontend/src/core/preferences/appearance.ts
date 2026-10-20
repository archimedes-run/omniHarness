import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

/**
 * Settings > Appearance, remembered per user on the server (Feature 006).
 *
 * The gateway stores the choice (GET/PUT /api/preferences/appearance);
 * next-themes' localStorage key ("theme") is only a cache so the last choice
 * paints before any request returns.
 */
export const APPEARANCES = ["system", "light", "dark"] as const;
export type Appearance = (typeof APPEARANCES)[number];

/** What the server said. `chosen: false` is "never chose", shown as System. */
export interface AppearancePreference {
  appearance: Appearance;
  chosen: boolean;
}

export function isAppearance(value: unknown): value is Appearance {
  return (
    typeof value === "string" &&
    (APPEARANCES as readonly string[]).includes(value)
  );
}

export function parseAppearancePreference(
  body: unknown,
): AppearancePreference | null {
  if (typeof body !== "object" || body === null) return null;
  const { appearance, chosen } = body as Record<string, unknown>;
  if (!isAppearance(appearance) || typeof chosen !== "boolean") return null;
  return { appearance, chosen };
}

const PATH = "/api/preferences/appearance";

/** The stored preference, or null when the server could not be asked. */
export async function fetchAppearance(): Promise<AppearancePreference | null> {
  try {
    const response = await fetch(`${getBackendBaseURL()}${PATH}`);
    if (!response.ok) return null;
    return parseAppearancePreference(await response.json());
  } catch {
    return null;
  }
}

export async function saveAppearance(
  appearance: Appearance,
): Promise<AppearancePreference> {
  const response = await fetch(`${getBackendBaseURL()}${PATH}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ appearance }),
  });
  const saved = response.ok
    ? parseAppearancePreference(await response.json())
    : null;
  if (!saved) throw new Error(`Could not save (${response.status}).`);
  return saved;
}

/**
 * An inline script that applies a stored appearance before first paint and
 * seeds next-themes' cache, so the server's value is what hydrates. The value
 * is checked against APPEARANCES before it is written into the script.
 */
export function appearanceScript(appearance: Appearance): string {
  if (!isAppearance(appearance)) return "";
  return `(function(){try{var t=${JSON.stringify(appearance)};localStorage.setItem("theme",t);var d=t==="system"?(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"):t;var e=document.documentElement;e.classList.remove("light","dark");e.classList.add(d);e.style.colorScheme=d}catch(_){}})()`;
}
