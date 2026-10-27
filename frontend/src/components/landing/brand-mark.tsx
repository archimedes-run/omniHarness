import { cn } from "@/lib/utils";

/** The OmniHarness mark: a ring on a rounded square, in theme tokens. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "bg-foreground inline-grid size-6 shrink-0 place-items-center rounded-md",
        className,
      )}
    >
      <span className="border-background size-2.5 rounded-full border-2" />
    </span>
  );
}
