/**
 * Connector brand icon, now drawn by the one logo registry
 * (src/components/brand). Kept as a name so existing callers do not move; an
 * unknown connector gets the registry's neutral monogram.
 */
import { BrandLogo } from "@/components/brand";

export function IntegrationIcon({
  slug,
  size = 20,
  label,
}: {
  slug: string | null | undefined;
  size?: number;
  label?: string;
}) {
  return <BrandLogo source={slug} name={label} size={size} />;
}
