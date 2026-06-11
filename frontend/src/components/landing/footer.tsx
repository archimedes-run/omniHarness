import { cn } from "@/lib/utils";

export type FooterProps = {
  className?: string;
};

const year = new Date().getFullYear();

export function Footer({ className }: FooterProps) {
  return (
    <footer
      className={cn(
        "w-full border-t border-stone-200 bg-white px-4 py-8 sm:px-6",
        className,
      )}
    >
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 text-center text-xs text-stone-400 sm:flex-row sm:text-left">
        <span>
          &copy; {year} OmniHarness · Open-source control plane for AI harnesses
        </span>
        <nav className="flex items-center gap-5">
          <a
            href="https://github.com/archimedes-run/omniHarness"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-stone-600"
          >
            GitHub
          </a>
          <a
            href="https://github.com/archimedes-run/omniHarness/blob/main/LICENSE"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-stone-600"
          >
            License
          </a>
          <a
            href="https://github.com/archimedes-run/omniHarness/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-stone-600"
          >
            Issues
          </a>
        </nav>
      </div>
    </footer>
  );
}
