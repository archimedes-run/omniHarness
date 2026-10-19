import { cn } from "@/lib/utils";

export type FooterProps = {
  className?: string;
};

const year = new Date().getFullYear();

export function Footer({ className }: FooterProps) {
  return (
    <footer
      className={cn(
        "border-border bg-card w-full border-t px-4 py-8 sm:px-6",
        className,
      )}
    >
      <div className="text-muted-foreground mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 text-center text-xs sm:flex-row sm:text-left">
        <span>
          &copy; {year} OmniHarness · Open-source control plane for AI harnesses
        </span>
        <nav className="flex items-center gap-5">
          <a
            href="https://github.com/archimedes-run/omniHarness"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-muted-foreground transition-colors"
          >
            GitHub
          </a>
          <a
            href="https://github.com/archimedes-run/omniHarness/blob/main/LICENSE"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-muted-foreground transition-colors"
          >
            License
          </a>
          <a
            href="https://github.com/archimedes-run/omniHarness/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-muted-foreground transition-colors"
          >
            Issues
          </a>
        </nav>
      </div>
    </footer>
  );
}
