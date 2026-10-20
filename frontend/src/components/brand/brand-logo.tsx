import { cn } from "@/lib/utils";

import { MONO_PATHS } from "./marks";
import { monogramFor, resolveBrand } from "./registry";

/**
 * A source's logo, from the one registry. Always an image with a name: a known
 * brand reads "<Brand> logo"; an unknown source gets a neutral monogram named
 * after the source itself, never an empty or decorative box.
 *
 * Clear space: the mark sits inside its box at about 70% of the box, so the
 * padding around it is never less than the brands' minimum clear space, and
 * the box is never drawn under 16 px.
 */
export function BrandLogo({
  source,
  name,
  size = 20,
  className,
  decorative = false,
}: {
  /** Any id the app uses: "connector:GMAIL", "local:github", "codex", … */
  source: string | null | undefined;
  /** The source's display name, for the fallback and its accessible name. */
  name?: string;
  size?: number;
  className?: string;
  /** True only when the same name is already spoken right next to it. */
  decorative?: boolean;
}) {
  const box = Math.max(16, size);
  const inner = Math.round(box * 0.7);
  const brand = resolveBrand(source) ?? resolveBrand(name);
  const label = brand
    ? `${brand.name} logo`
    : (name ?? source ?? "Unknown source");
  const a11y = decorative
    ? { "aria-hidden": true as const }
    : { role: "img", "aria-label": label };
  const boxClass = cn(
    "bg-surface-raised inline-flex shrink-0 items-center justify-center overflow-hidden rounded-md",
    className,
  );
  const dims = { width: box, height: box };

  if (brand?.logo?.kind === "file") {
    return (
      <span className={boxClass} style={dims} data-brand={brand.id} {...a11y}>
        <img
          src={brand.logo.src}
          alt=""
          width={inner}
          height={inner}
          className="object-contain"
        />
      </span>
    );
  }

  const path = brand?.logo?.kind === "mark" ? MONO_PATHS[brand.id] : undefined;
  if (path) {
    return (
      <span
        className={cn(boxClass, "text-foreground")}
        style={dims}
        data-brand={brand!.id}
        {...a11y}
      >
        <svg
          viewBox="0 0 24 24"
          width={inner}
          height={inner}
          fill="currentColor"
          aria-hidden
          focusable="false"
        >
          <path d={path} />
        </svg>
      </span>
    );
  }

  const text = brand?.monogram ?? monogramFor(name ?? source ?? "?");
  return (
    <span
      className={cn(
        boxClass,
        "text-foreground border-border border font-semibold",
      )}
      style={{
        ...dims,
        fontSize: Math.max(
          8,
          Math.round(box * (text.length > 2 ? 0.34 : 0.42)),
        ),
      }}
      data-brand={brand?.id ?? "monogram"}
      {...a11y}
    >
      <span aria-hidden>{text}</span>
    </span>
  );
}
