import { cn } from "@/lib/utils";

/** One block of a settings page, as a Graphite card (Feature 006): a 15 px
 * heading, a muted line, the controls. */
export function SettingsSection({
  className,
  title,
  description,
  children,
}: {
  className?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "bg-card border-border flex flex-col gap-3 rounded-xl border px-[18px] py-4",
        className,
      )}
    >
      {Boolean(title) || Boolean(description) ? (
        <header className="space-y-1">
          {title && <h2 className="text-[15px] font-semibold">{title}</h2>}
          {description && (
            <div className="text-muted-foreground text-sm">{description}</div>
          )}
        </header>
      ) : null}
      <div>{children}</div>
    </section>
  );
}
