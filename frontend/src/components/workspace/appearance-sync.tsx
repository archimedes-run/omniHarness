"use client";

import { useTheme } from "next-themes";
import { useEffect } from "react";

import {
  appearanceScript,
  fetchAppearance,
  type AppearancePreference,
} from "@/core/preferences";

/**
 * Applies the appearance stored on the server for this user.
 *
 * With `initial` (read during SSR), an inline script applies it before first
 * paint and seeds next-themes' cache, so there is no flash. Without it (SSR
 * could not tell), the client asks once and switches if the stored choice
 * differs from what this browser had cached.
 */
export function AppearanceSync({
  initial,
}: {
  initial: AppearancePreference | null;
}) {
  const { theme, setTheme } = useTheme();
  useEffect(() => {
    if (initial) return;
    let cancelled = false;
    void fetchAppearance().then((stored) => {
      if (!cancelled && stored?.chosen && stored.appearance !== theme) {
        setTheme(stored.appearance);
      }
    });
    return () => {
      cancelled = true;
    };
    // Once per load: re-running on every theme change would undo a choice
    // made on this page before the save returned.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  if (!initial?.chosen) return null;
  return (
    <script
      // Runs as the HTML is parsed, before the page paints.
      dangerouslySetInnerHTML={{ __html: appearanceScript(initial.appearance) }}
    />
  );
}
