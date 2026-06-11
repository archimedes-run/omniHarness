import { ArrowRightIcon, GitHubLogoIcon } from "@radix-ui/react-icons";
import Link from "next/link";

import { cn } from "@/lib/utils";

export function FinalCtaSection({ className }: { className?: string }) {
  return (
    <section
      className={cn(
        "mx-auto w-full max-w-6xl px-4 py-8 pb-20 sm:px-6 sm:pb-24",
        className,
      )}
    >
      <div className="rounded-[32px] bg-stone-950 px-6 py-12 text-center text-white shadow-[0_24px_70px_rgba(15,23,42,0.22)] sm:px-10">
        <p className="text-xs font-semibold tracking-[0.18em] text-white/55 uppercase">
          Build your first harness
        </p>
        <h2 className="mx-auto mt-4 max-w-3xl text-4xl font-bold tracking-tight text-balance sm:text-5xl">
          Start with a chat. End with a runnable AI capability.
        </h2>
        <p className="mx-auto mt-4 max-w-2xl text-base leading-relaxed text-pretty text-white/70">
          Build and operate agents, MCP tooling, workflows, previews, and
          governed execution from one self-hosted workspace.
        </p>
        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Link href="/workspace">
            <span className="inline-flex h-11 items-center gap-2 rounded-lg bg-white px-7 text-sm font-semibold text-stone-950 transition-colors hover:bg-stone-100">
              Start building
              <ArrowRightIcon className="size-4" />
            </span>
          </Link>
          <a
            href="https://github.com/archimedes-run/omniHarness"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-11 items-center gap-2 rounded-lg border border-white/16 bg-white/6 px-7 text-sm font-semibold text-white transition-colors hover:bg-white/10"
          >
            <GitHubLogoIcon className="size-4" />
            View on GitHub
          </a>
        </div>
      </div>
    </section>
  );
}
