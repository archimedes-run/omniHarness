/**
 * Spec 012 FR-014/FR-015: the gateway's SVG allowlist
 * (backend/app/gateway/artifacts_store/kinds.py `check_svg`), ported to the
 * frontend for the SVG that mermaid draws in its isolated frame. Two inert
 * attributes mermaid writes are added: `name` (sequence diagrams) and
 * `transform-origin` (gantt). A drawing that
 * fails is not shown (the source is, as code). One that passes is still only
 * ever shown as an `<img>` (scripts never run in an image).
 *
 * The check walks a parsed document; it never inserts the markup anywhere.
 */

const SVG_NS = "http://www.w3.org/2000/svg";
const XLINK_NS = "http://www.w3.org/1999/xlink";
const XML_NS = "http://www.w3.org/XML/1998/namespace";
const XMLNS_NS = "http://www.w3.org/2000/xmlns/";

const ELEMENTS = new Set(
  `svg g defs title desc symbol use path rect circle ellipse line polyline polygon text tspan textPath
  linearGradient radialGradient stop pattern clipPath mask marker filter image style
  feBlend feColorMatrix feComponentTransfer feFuncR feFuncG feFuncB feFuncA feComposite feConvolveMatrix
  feDiffuseLighting feDisplacementMap feDistantLight feDropShadow feFlood feGaussianBlur feMerge feMergeNode
  feMorphology feOffset fePointLight feSpecularLighting feSpotLight feTile feTurbulence`.split(
    /\s+/,
  ),
);

const ATTRIBUTES = new Set(
  `id class style transform x y x1 y1 x2 y2 cx cy r rx ry fx fy fr width height d points viewBox
  preserveAspectRatio version baseProfile fill fill-opacity fill-rule stroke stroke-width stroke-opacity
  stroke-linecap stroke-linejoin stroke-dasharray stroke-dashoffset stroke-miterlimit opacity color display
  visibility overflow clip-path clip-rule mask filter marker-start marker-mid marker-end font-family font-size
  font-weight font-style font-variant font-stretch text-anchor dominant-baseline alignment-baseline baseline-shift
  letter-spacing word-spacing text-decoration writing-mode dx dy rotate textLength lengthAdjust startOffset
  offset stop-color stop-opacity gradientUnits gradientTransform spreadMethod patternUnits patternContentUnits
  patternTransform clipPathUnits maskUnits maskContentUnits markerWidth markerHeight markerUnits refX refY orient
  filterUnits primitiveUnits in in2 result stdDeviation mode type values operator k1 k2 k3 k4 flood-color
  flood-opacity lighting-color radius scale xChannelSelector yChannelSelector baseFrequency numOctaves seed
  stitchTiles tableValues slope intercept amplitude exponent kernelMatrix order divisor bias targetX targetY
  edgeMode preserveAlpha surfaceScale diffuseConstant specularConstant specularExponent azimuth elevation z
  pointsAtX pointsAtY pointsAtZ limitingConeAngle kernelUnitLength href lang role media vector-effect
  shape-rendering text-rendering image-rendering color-interpolation color-interpolation-filters paint-order
  mix-blend-mode isolation pathLength
  name transform-origin`.split(/\s+/),
);

const URL_FN = /url\s*\(\s*(['"]?)(.*?)\1\s*\)/gis;
const DATA_IMAGE =
  /^data:image\/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\s]*$/i;
const BAD_VALUE =
  /javascript:|vbscript:|expression\(|-moz-binding|behavior:|@import/i;

export type SvgCheck = { ok: true } | { ok: false; reason: string };

function checkValue(value: string, where: string): string | null {
  const squashed = value.replace(/[\x00-\x20]+/g, "");
  if (value.includes("\\") || BAD_VALUE.test(squashed)) {
    return `${where} holds a script or an import`;
  }
  for (const m of value.matchAll(URL_FN)) {
    if (!(m[2] ?? "").trim().startsWith("#")) {
      return `${where} refers to an outside resource`;
    }
  }
  return null;
}

/** Check a parsed SVG document against the allowlist. */
export function checkSvgDocument(doc: Document): SvgCheck {
  if (doc.getElementsByTagName("parsererror").length) {
    return { ok: false, reason: "not well-formed" };
  }
  const root = doc.documentElement;
  if (root?.namespaceURI !== SVG_NS || root.localName !== "svg") {
    return { ok: false, reason: "the root is not <svg>" };
  }
  for (const node of Array.from(doc.childNodes)) {
    if (node.nodeType === 7 /* processing instruction */) {
      return { ok: false, reason: "a processing instruction" };
    }
    if (node.nodeType === 10 /* doctype */) {
      return { ok: false, reason: "a DOCTYPE" };
    }
  }
  const all = [root, ...Array.from(root.getElementsByTagName("*"))];
  for (const el of all) {
    if (el.namespaceURI !== SVG_NS) {
      return { ok: false, reason: "an element outside the SVG namespace" };
    }
    const name = el.localName;
    if (!ELEMENTS.has(name)) {
      return { ok: false, reason: `the element <${name.slice(0, 40)}>` };
    }
    for (const attr of Array.from(el.attributes)) {
      let local = attr.localName;
      if (attr.namespaceURI === XMLNS_NS) continue;
      if (attr.namespaceURI === XML_NS) {
        if (local === "space" || local === "lang") continue;
        return { ok: false, reason: "an attribute outside the SVG namespace" };
      }
      if (attr.namespaceURI === XLINK_NS) {
        if (local !== "href") {
          return {
            ok: false,
            reason: "an attribute outside the SVG namespace",
          };
        }
      } else if (attr.namespaceURI !== null) {
        return { ok: false, reason: "an attribute outside the SVG namespace" };
      }
      if (attr.name === "xmlns" || attr.name.startsWith("xmlns:")) continue;
      if (local.toLowerCase().startsWith("on")) {
        return { ok: false, reason: "an event attribute" };
      }
      if (local.includes(":")) local = local.split(":").pop()!;
      if (
        !ATTRIBUTES.has(local) &&
        !local.startsWith("aria-") &&
        !local.startsWith("data-")
      ) {
        return { ok: false, reason: `the attribute ${local.slice(0, 40)}` };
      }
      if (local === "href") {
        const target = attr.value.trim();
        if (
          !(
            target.startsWith("#") ||
            (name === "image" && DATA_IMAGE.test(target))
          )
        ) {
          return { ok: false, reason: "a link outside the SVG" };
        }
        continue;
      }
      const bad = checkValue(attr.value, `the attribute ${local}`);
      if (bad) return { ok: false, reason: bad };
    }
    if (name === "style") {
      const bad = checkValue(el.textContent ?? "", "a <style> block");
      if (bad) return { ok: false, reason: bad };
    }
  }
  return { ok: true };
}

/** Parse (as XML, never as HTML in the page) and check. `parse` is the
 * browser's DOMParser unless a test passes its own. */
export function checkSvgText(
  text: string,
  parse?: (text: string) => Document,
): SvgCheck {
  if (/<\?xml-stylesheet/i.test(text)) {
    return { ok: false, reason: "an xml-stylesheet instruction" };
  }
  if (/<!DOCTYPE|<!ENTITY/i.test(text)) {
    return { ok: false, reason: "a DOCTYPE or entity" };
  }
  let doc: Document;
  if (parse) {
    doc = parse(text);
  } else if (typeof DOMParser === "undefined") {
    return { ok: false, reason: "no parser" };
  } else {
    doc = new DOMParser().parseFromString(text, "image/svg+xml");
  }
  return checkSvgDocument(doc);
}

/** An SVG as an image URL (never markup in the page). */
export function svgDataUrl(svg: string): string {
  const bytes = new TextEncoder().encode(svg);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return `data:image/svg+xml;base64,${btoa(bin)}`;
}
