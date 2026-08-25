"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";

export function ThemeProvider({
  children,
  ...props
}: React.ComponentProps<typeof NextThemesProvider>) {
  // NO forcedTheme HERE. It used to say forcedTheme="light", placed AFTER the
  // spread so it overrode anything layout.tsx passed and anything the user
  // chose: next-themes pinned <html class="light"> forever and every theme
  // control in the app was inert.
  //
  // It was added in a design-polish commit at a time when .dark duplicated
  // :root for 24 of its 31 tokens — pinning to light then cost nothing visible,
  // because there was no dark theme to switch to. PR #20 gave those tokens real
  // values and the pin became the thing standing between the user and a working
  // toggle. It survived that PR because the test there parses the stylesheet,
  // and no stylesheet assertion can see a provider prop.
  return <NextThemesProvider {...props}>{children}</NextThemesProvider>;
}
