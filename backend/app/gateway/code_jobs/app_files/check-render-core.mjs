/*
 * The app kit's render check, without a browser (Spec 011 FR-025).
 *
 * A minimal in-memory DOM, enough for react-dom/client, and the kit's mock
 * shim: the app's root component is rendered once per mock state (fresh,
 * empty, not_connected, failed), its effects run and its data arrives, as in
 * the page. Any error React reports comes back with its full message and
 * component stack, so a crash such as "Rendered more hooks than during the
 * previous render" is found in the sandbox, before the system's browser check.
 *
 * Used by omni-kit/check-render.mjs (which bundles the app with Vite). Plain
 * JavaScript, no dependency beyond the app's own react and react-dom.
 */

class Node {
  constructor(doc, nodeType, nodeName) {
    this.ownerDocument = doc;
    this.nodeType = nodeType;
    this.nodeName = nodeName;
    this.childNodes = [];
    this.parentNode = null;
    this._listeners = {};
  }
  get firstChild() {
    return this.childNodes[0] || null;
  }
  get lastChild() {
    return this.childNodes[this.childNodes.length - 1] || null;
  }
  get nextSibling() {
    if (!this.parentNode) return null;
    const list = this.parentNode.childNodes;
    return list[list.indexOf(this) + 1] || null;
  }
  get previousSibling() {
    if (!this.parentNode) return null;
    const list = this.parentNode.childNodes;
    return list[list.indexOf(this) - 1] || null;
  }
  get parentElement() {
    return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null;
  }
  appendChild(child) {
    return this.insertBefore(child, null);
  }
  insertBefore(child, ref) {
    if (child.nodeType === 11) {
      for (const c of [...child.childNodes]) this.insertBefore(c, ref);
      return child;
    }
    if (child.parentNode) child.parentNode.removeChild(child);
    const at = ref ? this.childNodes.indexOf(ref) : -1;
    if (at < 0) this.childNodes.push(child);
    else this.childNodes.splice(at, 0, child);
    child.parentNode = this;
    return child;
  }
  removeChild(child) {
    const at = this.childNodes.indexOf(child);
    if (at >= 0) this.childNodes.splice(at, 1);
    child.parentNode = null;
    return child;
  }
  contains(other) {
    for (let n = other; n; n = n.parentNode) if (n === this) return true;
    return false;
  }
  get textContent() {
    if (this.nodeType === 3 || this.nodeType === 8) return this.nodeValue;
    return this.childNodes.map((c) => (c.nodeType === 8 ? "" : c.textContent)).join("");
  }
  set textContent(value) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = [];
    if (value !== "" && value != null) this.appendChild(this.ownerDocument.createTextNode(String(value)));
  }
  addEventListener(type, fn) {
    (this._listeners[type] ||= []).push(fn);
  }
  removeEventListener(type, fn) {
    const list = this._listeners[type] || [];
    const at = list.indexOf(fn);
    if (at >= 0) list.splice(at, 1);
  }
  dispatchEvent() {
    return true;
  }
  getRootNode() {
    let n = this;
    while (n.parentNode) n = n.parentNode;
    return n;
  }
}

class Text extends Node {
  constructor(doc, value, type = 3) {
    super(doc, type, type === 3 ? "#text" : "#comment");
    this.nodeValue = value;
  }
  get data() {
    return this.nodeValue;
  }
  set data(v) {
    this.nodeValue = v;
  }
}

function styleObject() {
  const values = {};
  return new Proxy(values, {
    get(target, key) {
      if (key === "setProperty") return (k, v) => (target[k] = String(v));
      if (key === "removeProperty") return (k) => delete target[k];
      if (key === "getPropertyValue") return (k) => target[k] || "";
      if (key === "cssText") return Object.entries(target).map(([k, v]) => `${k}: ${v}`).join("; ");
      return target[key] ?? "";
    },
    set(target, key, value) {
      target[key] = String(value);
      return true;
    },
  });
}

class Element extends Node {
  constructor(doc, tag, ns) {
    super(doc, 1, tag.toUpperCase());
    this.tagName = this.nodeName;
    this.localName = tag;
    this.namespaceURI = ns || "http://www.w3.org/1999/xhtml";
    this.attributes = {};
    this.style = styleObject();
    const classes = new Set();
    this.classList = {
      add: (...c) => c.forEach((x) => classes.add(x)),
      remove: (...c) => c.forEach((x) => classes.delete(x)),
      contains: (c) => classes.has(c),
      toggle: (c) => (classes.has(c) ? (classes.delete(c), false) : (classes.add(c), true)),
    };
  }
  setAttribute(k, v) {
    this.attributes[k] = String(v);
  }
  setAttributeNS(_ns, k, v) {
    this.attributes[k] = String(v);
  }
  getAttribute(k) {
    return k in this.attributes ? this.attributes[k] : null;
  }
  removeAttribute(k) {
    delete this.attributes[k];
  }
  removeAttributeNS(_ns, k) {
    delete this.attributes[k];
  }
  hasAttribute(k) {
    return k in this.attributes;
  }
  get innerHTML() {
    return "";
  }
  set innerHTML(_v) {
    throw new TypeError("This document requires 'TrustedHTML' assignment (apps may not set innerHTML).");
  }
  get className() {
    return this.attributes.class || "";
  }
  set className(v) {
    this.attributes.class = String(v);
  }
  get children() {
    return this.childNodes.filter((c) => c.nodeType === 1);
  }
  focus() {
    this.ownerDocument.activeElement = this;
  }
  blur() {}
  getBoundingClientRect() {
    return { x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 };
  }
}

class Document extends Node {
  constructor(win) {
    super(null, 9, "#document");
    this.ownerDocument = null;
    this.defaultView = win;
    this.documentElement = this.createElement("html");
    this.head = this.createElement("head");
    this.body = this.createElement("body");
    this.documentElement.appendChild(this.head);
    this.documentElement.appendChild(this.body);
    this.appendChild(this.documentElement);
    this.activeElement = this.body;
    this.readyState = "complete";
  }
  createElement(tag) {
    return new Element(this, String(tag).toLowerCase());
  }
  createElementNS(ns, tag) {
    return new Element(this, String(tag), ns);
  }
  createTextNode(v) {
    return new Text(this, String(v));
  }
  createComment(v) {
    return new Text(this, String(v), 8);
  }
  createDocumentFragment() {
    const f = new Node(this, 11, "#document-fragment");
    return f;
  }
  getElementById() {
    return null;
  }
  querySelector() {
    return null;
  }
  querySelectorAll() {
    return [];
  }
}

/** A fresh window and document for one state. */
export function makeWindow(search) {
  const win = {
    location: { search, href: "http://app.local/" + search, hash: "" },
    navigator: { userAgent: "omni-check-render" },
    HTMLIFrameElement: class {},
    HTMLElement: Element,
    Element,
    Node,
    Text,
    event: undefined,
    getComputedStyle: () => styleObject(),
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
    requestAnimationFrame: (fn) => setTimeout(() => fn(Date.now()), 0),
    cancelAnimationFrame: (id) => clearTimeout(id),
    getSelection: () => null,
    addEventListener() {},
    removeEventListener() {},
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
  };
  win.document = new Document(win);
  win.window = win;
  win.self = win;
  win.parent = win;
  win.top = win;
  return win;
}

function clip(text, n) {
  const s = String(text == null ? "" : text);
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function describe(value) {
  if (value instanceof Error) {
    const frames = String(value.stack || "").split("\n").filter((l) => l.trim().startsWith("at ")).slice(0, 4);
    return [`${value.name}: ${value.message}`, ...frames.map((f) => "    " + f.trim())].join("\n");
  }
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/**
 * Render `App` once per mock state. `env`: { React, ReactDOMClient, act,
 * App, mockShim (the kit's omni-mock.js text, with its data) }. Returns
 * { ok, results: [{ state, ok, text_length, errors: [{ message,
 * component_stack }], console: [...] }] }.
 */
export async function checkRender(env) {
  const { React, ReactDOMClient, act, App, mockShim } = env;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const results = [];
  const realConsoleError = console.error;
  const realConsoleWarn = console.warn;
  for (const state of ["fresh", "empty", "not_connected", "failed"]) {
    const win = makeWindow(`?state=${state}&theme=light`);
    globalThis.window = win;
    globalThis.document = win.document;
    globalThis.navigator ??= win.navigator;
    new Function("window", "document", mockShim)(win, win.document);
    globalThis.omni = win.omni;
    const errors = [];
    const logged = [];
    const record = (level) => (...args) => {
      const rest = [...args];
      let head = typeof rest[0] === "string" ? rest.shift() : "";
      head = head.replace(/%[sdoOif]/g, () => (rest.length ? describe(rest.shift()) : ""));
      const text = clip([head, ...rest.map(describe)].filter(Boolean).join(" "), 600);
      if (!logged.some((l) => l.text === text) && logged.length < 10) logged.push({ level, text });
    };
    console.error = record("error");
    console.warn = record("warn");
    const onError = (kind) => (error, info) => {
      errors.push({ kind, message: clip(describe(error), 600), component_stack: clip(info && info.componentStack, 1200) });
    };
    const container = win.document.createElement("div");
    win.document.body.appendChild(container);
    let root;
    try {
      root = ReactDOMClient.createRoot(container, {
        onUncaughtError: onError("uncaught"),
        onCaughtError: onError("caught"),
        onRecoverableError: onError("recoverable"),
      });
      await act(async () => {
        root.render(React.createElement(App));
      });
      // The mock answers after 30 ms; updates and effects settle after that.
      await act(async () => {
        await new Promise((r) => setTimeout(r, 200));
      });
    } catch (error) {
      errors.push({ kind: "thrown", message: clip(describe(error), 600), component_stack: "" });
    }
    const text = container.textContent.trim();
    try {
      await act(async () => root && root.unmount());
    } catch {
      /* already broken */
    }
    console.error = realConsoleError;
    console.warn = realConsoleWarn;
    const ok = errors.length === 0 && text.length > 0;
    results.push({ state, ok, text_length: text.length, errors, console: logged });
  }
  return { ok: results.every((r) => r.ok), results };
}

/** The results in words, for the worker's terminal. */
export function report(outcome) {
  const lines = [];
  for (const r of outcome.results) {
    lines.push(`${r.ok ? "ok  " : "FAIL"} ${r.state}: ${r.text_length ? `${r.text_length} characters rendered` : "rendered nothing"}`);
    for (const e of r.errors) {
      lines.push(`  ${e.kind} error: ${e.message}`);
      if (e.component_stack) lines.push(`  component stack:${e.component_stack}`);
    }
    for (const c of r.console) lines.push(`  console.${c.level}: ${c.text}`);
  }
  lines.push(outcome.ok ? "check:render passed" : "check:render FAILED: fix the first error above (its component stack names the component)");
  return lines.join("\n");
}
