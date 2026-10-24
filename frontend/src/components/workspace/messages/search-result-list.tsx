import type { SearchResultItem } from "@/core/tools/search-results";

/**
 * A search step's results: one row each, the title as an ordinary link (a
 * new tab, no referrer, no opener), its site, one line of snippet. Shown in
 * the steps area, collapsed with them. No image and no preview is ever loaded
 * from a result (zero-click exfiltration fix): everything here is text the
 * display sanitiser made safe (core/tools/search-results.ts).
 */
export function SearchResultList({ items }: { items: SearchResultItem[] }) {
  if (items.length === 0) {
    return (
      <p className="text-muted-foreground text-xs" data-testid="search-results">
        No results.
      </p>
    );
  }
  return (
    <ol className="flex flex-col gap-2" data-testid="search-results">
      {items.map((item, index) => (
        <li
          key={`${item.href ?? item.title}-${index}`}
          className="min-w-0 text-sm"
          data-testid="search-result"
        >
          <div className="flex min-w-0 items-baseline gap-2">
            {item.href ? (
              <a
                href={item.href}
                target="_blank"
                rel="noopener noreferrer nofollow"
                referrerPolicy="no-referrer"
                className="text-foreground truncate font-medium underline-offset-2 hover:underline"
              >
                {item.title || item.host}
              </a>
            ) : (
              <span className="text-foreground truncate font-medium">
                {item.title}
              </span>
            )}
            {item.host && (
              <span className="text-muted-foreground shrink-0 text-xs">
                {item.host}
              </span>
            )}
          </div>
          {item.snippet && (
            <p className="text-muted-foreground truncate text-xs">
              {item.snippet}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
