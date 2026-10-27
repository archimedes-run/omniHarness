import { cn } from "@/lib/utils";

/** A landing section's H2 and its one-line lead, centred. */
export function SectionHeading({
  id,
  title,
  lead,
  className,
}: {
  id: string;
  title: string;
  lead?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mx-auto max-w-2xl text-center", className)}>
      <h2
        id={`${id}-title`}
        className="text-foreground text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
      >
        {title}
      </h2>
      {lead && (
        <p className="text-foreground-2 mt-3 text-base leading-relaxed text-pretty">
          {lead}
        </p>
      )}
    </div>
  );
}
