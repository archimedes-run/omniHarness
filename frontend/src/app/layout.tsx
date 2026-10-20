import "@/styles/globals.css";

import { type Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { ThemeProvider } from "@/components/theme-provider";
import { I18nProvider } from "@/core/i18n/context";
import { detectLocaleServer } from "@/core/i18n/server";

// Self-hosted: next/font downloads these at build time and serves them from
// this app, so no page ever asks a font CDN for anything.
const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-inter",
  display: "swap",
});
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
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
