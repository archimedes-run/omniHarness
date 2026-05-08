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
  return (
    <header
      className={cn(
        "fixed inset-x-0 top-0 z-50 px-4 pt-4",
        className,
      )}
    >
      {/* Floating pill navbar */}
      <nav className="mx-auto flex max-w-4xl items-center justify-between rounded-2xl border border-stone-200/80 bg-[#F5F0E8]/80 px-5 py-2.5 shadow-sm backdrop-blur-md">
        {/* Logo */}
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

        {/* Centre nav links */}
        <div className="hidden items-center gap-7 text-sm font-medium text-stone-500 sm:flex">
          <a
            href="https://github.com/archimedes-run/omni-harness#readme"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-stone-800"
          >
            Docs
          </a>
          <a
            href="https://github.com/archimedes-run/omni-harness/releases"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-stone-800"
          >
            Changelog
          </a>
          <a
            href="https://github.com/archimedes-run/omni-harness/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-stone-800"
          >
            Community
          </a>
        </div>

        {/* CTA */}
        <a
          href="https://github.com/archimedes-run/omni-harness"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-lg border border-stone-300 bg-white/60 px-3.5 py-1.5 text-xs font-semibold text-stone-700 transition-colors hover:border-stone-400 hover:bg-white/80"
        >
          <GitHubLogoIcon className="size-3.5" />
          GitHub
        </a>
      </nav>
    </header>
  );
}
