/**
 * Connector brand-icon registry. Real brand marks served from
 * public/icons/integrations/, keyed by toolkit slug. All 8 supported connectors
 * have an asset; the neutral mail glyph is only for a future/unknown connector.
 */
import { Mail } from "lucide-react";

// Toolkit slug (uppercase) → served asset path.
const ASSET: Record<string, string> = {
  GMAIL: "/icons/integrations/gmail.webp",
  GOOGLECALENDAR: "/icons/integrations/googlecalendar.webp",
  GOOGLEDRIVE: "/icons/integrations/googledrive.webp",
  SLACK: "/icons/integrations/slack.svg",
  NOTION: "/icons/integrations/notion.webp",
  GITHUB: "/icons/integrations/github.svg",
  LINEAR: "/icons/integrations/linear.webp",
  OUTLOOK: "/icons/integrations/outlook.webp",
};

export function IntegrationIcon({
  slug,
  size = 20,
  label,
}: {
  slug: string | null | undefined;
  size?: number;
  label?: string;
}) {
  const src = slug ? ASSET[slug.toUpperCase()] : undefined;
  if (!src) {
    // Any future/unknown connector without an asset → neutral mail glyph.
    return (
      <Mail
        style={{ width: size, height: size }}
        aria-label={label}
        aria-hidden={label ? undefined : true}
      />
    );
  }
  // Plain <img>: static public asset, no next/image config needed.

  return (
    <img
      src={src}
      width={size}
      height={size}
      alt={label ?? ""}
      className="object-contain"
      loading="lazy"
    />
  );
}
