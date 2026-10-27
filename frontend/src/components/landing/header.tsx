"use client";

import {
  Cross2Icon,
  GitHubLogoIcon,
  HamburgerMenuIcon,
} from "@radix-ui/react-icons";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { BrandMark } from "./brand-mark";
import { GITHUB_URL, NAV_LINKS } from "./links";

export type HeaderProps = {
  className?: string;
  homeURL?: string;
  locale?: string;
};

export function Header({ className, homeURL }: HeaderProps) {
  const [open, setOpen] = useState(false);

  return (
    <header
      className={cn(
        "border-border bg-background sticky inset-x-0 top-0 z-50 w-full border-b",
        className,
      )}
    >
      <nav
        aria-label="Main"
        className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6"
      >
        <Link
          href={homeURL ?? "/"}
          className="text-foreground flex items-center gap-2"
        >
          <BrandMark />
          <span className="text-sm font-semibold tracking-tight">
            OmniHarness
          </span>
        </Link>

        <div className="text-foreground-2 hidden items-center gap-6 text-sm md:flex">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="hover:text-foreground transition-colors"
            >
              {link.label}
            </Link>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer">
              <GitHubLogoIcon className="size-3.5" />
              GitHub
            </a>
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className="md:hidden"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            aria-controls="landing-mobile-menu"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <Cross2Icon /> : <HamburgerMenuIcon />}
          </Button>
        </div>
      </nav>

      {open && (
        <div
          id="landing-mobile-menu"
          className="border-border bg-background border-t md:hidden"
        >
          <ul className="mx-auto flex max-w-6xl flex-col px-4 py-2 sm:px-6">
            {NAV_LINKS.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  onClick={() => setOpen(false)}
                  className="text-foreground hover:bg-muted block rounded-md px-2 py-2.5 text-sm"
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </header>
  );
}
