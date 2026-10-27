import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { SECTION_IDS } from "../links";

import { SectionHeading } from "./section-heading";

const TIERS = [
  {
    label: "Reads freely",
    text: "Searching, reading mail, checking the calendar: reads run without asking.",
    accent: "border-l-success",
  },
  {
    label: "Does, then tells you",
    text: "Reversible changes run and are shown to you with an Undo.",
    accent: "border-l-primary",
  },
  {
    label: "Asks first",
    text: "Anything that sends, deletes, shares or spends waits for your Confirm.",
    accent: "border-l-warning",
  },
];

const RULES = [
  "Tools without a rule are refused, never defaulted.",
  "Content an agent reads can suggest, never approve.",
  "Automation run history is encrypted on your disk.",
];

const INERT = "pointer-events-none cursor-default";

/** A drawing of an approval card, not a live control. */
function ApprovalCard() {
  return (
    <figure
      aria-label="An approval card waiting for your Confirm"
      className="border-border bg-card mx-auto mt-10 w-full max-w-lg rounded-xl border p-4 text-left sm:p-5"
    >
      <p className="text-warning text-xs font-semibold">Needs your approval</p>
      <p className="text-foreground mt-1.5 text-sm">
        Inbox agent will delete 14 emails: newsletters older than 30 days.
      </p>
      <p className="text-muted-foreground mt-1 text-xs">
        Nothing happens until you choose.
      </p>
      {/* Drawn buttons: not focusable, not clickable, no hover. */}
      <div
        aria-hidden
        className="pointer-events-none mt-4 flex justify-end gap-2 select-none"
      >
        <span
          className={cn(
            buttonVariants({ variant: "outline", size: "sm" }),
            INERT,
          )}
        >
          Decline
        </span>
        <span className={cn(buttonVariants({ size: "sm" }), INERT)}>
          Confirm
        </span>
      </div>
    </figure>
  );
}

export function SafetySection() {
  const id = SECTION_IDS.safety;
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className="border-border scroll-mt-20 border-t px-4 py-16 sm:px-6 sm:py-20"
    >
      <SectionHeading
        id={id}
        title="Safe by design"
        lead="Every tool call is sorted into one of three tiers before it runs."
      />
      <ol className="mx-auto mt-10 grid max-w-5xl grid-cols-1 gap-4 md:grid-cols-3">
        {TIERS.map((tier) => (
          <li
            key={tier.label}
            className={cn(
              "border-border bg-card rounded-xl border border-l-4 p-5",
              tier.accent,
            )}
          >
            <h3 className="text-foreground text-base font-semibold">
              {tier.label}
            </h3>
            <p className="text-foreground-2 mt-1.5 text-sm leading-relaxed">
              {tier.text}
            </p>
          </li>
        ))}
      </ol>
      <ul className="text-foreground-2 mx-auto mt-8 flex max-w-3xl flex-col gap-2 text-center text-sm sm:text-base">
        {RULES.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      <ApprovalCard />
    </section>
  );
}
