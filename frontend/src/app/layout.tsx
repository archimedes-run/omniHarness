import "@/styles/globals.css";

import { type Metadata } from "next";
import localFont from "next/font/local";

import { ThemeProvider } from "@/components/theme-provider";
import { I18nProvider } from "@/core/i18n/context";
import { detectLocaleServer } from "@/core/i18n/server";

// Inter and JetBrains Mono ship in the repo (public/fonts/, SIL OFL 1.1, see
// Inter-OFL.txt and JetBrainsMono-OFL.txt there): no build, CI run or page
// ever fetches a font from Google. These are the variable-font latin subsets Next's Google font
// loader used to download; next/font/local preloads them and generates the
// size-adjusted fallback, as before. The latin-ext subsets cannot be given a
// unicode-range here, so they are declared with @font-face in
// src/styles/globals.css and sit ahead of these families in --font-sans and
// --font-mono.
const inter = localFont({
  src: "../../public/fonts/inter-latin.woff2",
  weight: "400 600",
  style: "normal",
  variable: "--font-inter",
  display: "swap",
});
const jetbrainsMono = localFont({
  src: "../../public/fonts/jetbrains-mono-latin.woff2",
  weight: "400 500",
  style: "normal",
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "OmniHarness",
  description: "A LangChain-based framework for building super agents.",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = await detectLocaleServer();
  return (
    <html
      lang={locale}
      className={`${inter.variable} ${jetbrainsMono.variable}`}
      suppressContentEditableWarning
      suppressHydrationWarning
    >
      <body className="font-sans antialiased">
        {/* enableSystem is TRUE because the settings page offers a "System"
            option. It previously did not, so that control was inert — a
            control that cannot work is worse than an absent one, because the
            user believes they have made a choice.

            defaultTheme is "system" (Feature 006): until a user chooses, the
            app follows the OS. The choice is stored per user on the server
            (GET/PUT /api/preferences/appearance) and applied before paint by
            AppearanceSync in the workspace layout; localStorage caches it. */}
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <I18nProvider initialLocale={locale}>{children}</I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
