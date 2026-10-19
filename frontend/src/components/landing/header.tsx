"use client";

import { GitHubLogoIcon } from "@radix-ui/react-icons";
import Link from "next/link";

import { cn } from "@/lib/utils";

export type HeaderProps = {
  className?: string;
  homeURL?: string;
  locale?: string;
};

export function Header({ className, homeURL }: HeaderProps) {
  const links = [
    { href: "#what-is", label: "Platform" },
    { href: "#orchestration", label: "Orchestration" },
    { href: "#platform", label: "Suite" },
    { href: "#workbench", label: "Workbench" },
  ];

  return (
    <header className={cn("fixed inset-x-0 top-0 z-50 px-4 pt-4", className)}>
      <nav className="border-border bg-card/92 mx-auto flex max-w-5xl items-center justify-between rounded-2xl border px-4 py-2.5 shadow-[0_10px_30px_rgba(15,23,42,0.06)] backdrop-blur-md sm:px-5">
        <Link
          href={homeURL ?? "/"}
          className="text-foreground flex items-center gap-2"
        >
          <span className="bg-primary text-primary-foreground flex size-6 items-center justify-center rounded-md text-[10px] font-bold">
            O
          </span>
          <span className="text-sm font-semibold tracking-tight">
            OmniHarness
          </span>
        </Link>

        <div className="text-muted-foreground hidden items-center gap-6 text-sm font-medium md:flex">
          {links.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="hover:text-foreground transition-colors"
            >
              {link.label}
            </a>
          ))}
        </div>

        <a
          href="https://github.com/archimedes-run/omniHarness"
          target="_blank"
          rel="noopener noreferrer"
          className="border-border bg-primary text-primary-foreground hover:bg-primary/90 inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors sm:px-3.5"
        >
          <GitHubLogoIcon className="size-3.5" />
          GitHub
        </a>
      </nav>
    </header>
  );
}
