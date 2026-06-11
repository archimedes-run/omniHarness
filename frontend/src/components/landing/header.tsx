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
      <nav className="mx-auto flex max-w-5xl items-center justify-between rounded-2xl border border-stone-200 bg-white/92 px-4 py-2.5 shadow-[0_10px_30px_rgba(15,23,42,0.06)] backdrop-blur-md sm:px-5">
        <Link
          href={homeURL ?? "/"}
          className="flex items-center gap-2 text-stone-900"
        >
          <span className="flex size-6 items-center justify-center rounded-md bg-stone-900 text-[10px] font-bold text-white">
            O
          </span>
          <span className="text-sm font-semibold tracking-tight">
            OmniHarness
          </span>
        </Link>

        <div className="hidden items-center gap-6 text-sm font-medium text-stone-500 md:flex">
          {links.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="transition-colors hover:text-stone-900"
            >
              {link.label}
            </a>
          ))}
        </div>

        <a
          href="https://github.com/archimedes-run/omniHarness"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-lg border border-stone-300 bg-stone-950 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-stone-800 sm:px-3.5"
        >
          <GitHubLogoIcon className="size-3.5" />
          GitHub
        </a>
      </nav>
    </header>
  );
}
