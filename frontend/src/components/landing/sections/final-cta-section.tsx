import { ArrowRightIcon } from "@radix-ui/react-icons";
import Link from "next/link";

import { Button } from "@/components/ui/button";

import { DOCS_URL } from "../links";

export function FinalCtaSection() {
  return (
    <section
      aria-labelledby="run-it-title"
      className="border-border border-t px-4 py-16 sm:px-6 sm:py-20"
    >
      <div className="border-border bg-card mx-auto max-w-3xl rounded-2xl border px-6 py-12 text-center sm:px-10">
        <h2
          id="run-it-title"
          className="text-foreground text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
        >
          Runs on your machine
        </h2>
        <p className="text-foreground-2 mx-auto mt-3 max-w-xl text-base leading-relaxed text-pretty">
          One owner, local-first, with your own model keys. Start the stack with
          Docker Compose and open it in your browser.
        </p>
        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Button asChild size="lg">
            <Link href="/workspace">
              Get started
              <ArrowRightIcon />
            </Link>
          </Button>
          <Button asChild size="lg" variant="outline">
            <Link href={DOCS_URL}>Read the docs</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}
