/**
 * A tiny, strict XML parser for unit tests only: it builds just the parts of
 * the DOM that svg-allowlist.ts `checkSvgDocument` reads (namespaces resolved
 * from xmlns declarations, attributes, descendants, text, processing
 * instructions). Malformed input yields a document holding <parsererror>, as
 * the browser's DOMParser does. The browser path itself is covered by the
 * rendering specs.
 */

interface Attr {
  name: string;
  localName: string;
  namespaceURI: string | null;
  value: string;
}

interface Node {
  nodeType: number;
}

class El implements Node {
  nodeType = 1;
  children: El[] = [];
  text = "";
  constructor(
    public localName: string,
    public namespaceURI: string | null,
    public attributes: Attr[],
  ) {}
  getElementsByTagName(name: string): El[] {
    const out: El[] = [];
    const walk = (e: El) => {
      for (const c of e.children) {
        if (name === "*" || c.localName === name) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  get textContent(): string {
    return this.text + this.children.map((c) => c.textContent).join("");
  }
}

const XML_NS = "http://www.w3.org/XML/1998/namespace";
const XMLNS_NS = "http://www.w3.org/2000/xmlns/";

function decode(v: string) {
  return v
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

export function parseXml(text: string): Document {
  const root = new El("#document", null, []);
  const childNodes: Node[] = [];
  const error = () => {
    const d = new El("#document", null, []);
    d.children.push(new El("parsererror", null, []));
    return {
      documentElement: d.children[0],
      childNodes: [d.children[0]],
      getElementsByTagName: (n: string) => d.getElementsByTagName(n),
    } as unknown as Document;
  };
  const stack: { el: El; ns: Map<string, string> }[] = [
    { el: root, ns: new Map([["xml", XML_NS]]) },
  ];
  let i = 0;
  while (i < text.length) {
    if (text.startsWith("<?", i)) {
      const end = text.indexOf("?>", i);
      if (end < 0) return error();
      if (stack.length === 1) childNodes.push({ nodeType: 7 });
      i = end + 2;
    } else if (text.startsWith("<!--", i)) {
      const end = text.indexOf("-->", i);
      if (end < 0) return error();
      i = end + 3;
    } else if (text.startsWith("<!", i)) {
      const end = text.indexOf(">", i);
      if (end < 0) return error();
      if (stack.length === 1) childNodes.push({ nodeType: 10 });
      i = end + 1;
    } else if (text.startsWith("</", i)) {
      const end = text.indexOf(">", i);
      const name = text.slice(i + 2, end).trim();
      const top = stack.pop();
      if (!top || stack.length === 0) return error();
      const local = name.includes(":") ? name.split(":")[1] : name;
      if (top.el.localName !== local) return error();
      i = end + 1;
    } else if (text[i] === "<") {
      const m =
        /^<([A-Za-z_][\w.:-]*)((?:\s+[^\s=/>]+\s*=\s*(?:"[^"]*"|'[^']*'))*)\s*(\/?)>/.exec(
          text.slice(i),
        );
      if (!m) return error();
      const parent = stack[stack.length - 1]!;
      const ns = new Map(parent.ns);
      const raw: [string, string][] = [];
      for (const a of m[2]!.matchAll(
        /([^\s=/>]+)\s*=\s*("([^"]*)"|'([^']*)')/g,
      )) {
        raw.push([a[1]!, decode(a[3] ?? a[4] ?? "")]);
      }
      for (const [n, v] of raw) {
        if (n === "xmlns") ns.set("", v);
        else if (n.startsWith("xmlns:")) ns.set(n.slice(6), v);
      }
      const attrs: Attr[] = raw.map(([n, v]) => {
        if (n === "xmlns" || n.startsWith("xmlns:"))
          return {
            name: n,
            localName: n.split(":").pop()!,
            namespaceURI: XMLNS_NS,
            value: v,
          };
        if (n.includes(":")) {
          const [p, l] = n.split(":") as [string, string];
          return {
            name: n,
            localName: l,
            namespaceURI: ns.get(p) ?? null,
            value: v,
          };
        }
        return { name: n, localName: n, namespaceURI: null, value: v };
      });
      const tag = m[1]!;
      const [prefix, local] = tag.includes(":")
        ? (tag.split(":") as [string, string])
        : ["", tag];
      const el = new El(local, ns.get(prefix) ?? null, attrs);
      parent.el.children.push(el);
      if (stack.length === 1) childNodes.push(el);
      if (!m[3]) stack.push({ el, ns });
      i += m[0].length;
    } else {
      const end = text.indexOf("<", i);
      const chunk = text.slice(i, end < 0 ? undefined : end);
      if (stack.length === 1 && chunk.trim()) return error();
      stack[stack.length - 1]!.el.text += decode(chunk);
      i = end < 0 ? text.length : end;
    }
  }
  if (stack.length !== 1 || root.children.length !== 1) return error();
  return {
    documentElement: root.children[0],
    childNodes,
    getElementsByTagName: (n: string) => root.getElementsByTagName(n),
  } as unknown as Document;
}
