export const GITHUB_URL = "https://github.com/archimedes-run/omniHarness";
// The in-app docs route (/en/docs) fails to render in a production build,
// so the docs links go to the README on GitHub until that is fixed.
export const DOCS_URL = `${GITHUB_URL}#readme`;

/**
 * The landing sections the header links to. The anchors are written `/#id`,
 * not `#id`: the header is also the navbar of the blog and the docs, where a
 * bare `#id` would point at an id on that page instead of the landing page.
 * tests/unit/landing.test.ts checks each one resolves to a rendered id.
 */
export const SECTION_IDS = {
  product: "product",
  day: "day",
  safety: "safety",
} as const;

export const NAV_LINKS = [
  { href: `/#${SECTION_IDS.product}`, label: "Product" },
  { href: `/#${SECTION_IDS.day}`, label: "A day with it" },
  { href: `/#${SECTION_IDS.safety}`, label: "Safety" },
  { href: DOCS_URL, label: "Docs" },
] as const;
