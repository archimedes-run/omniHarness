/* OmniHarness artifact frame shim (Spec 012 FR-016, FR-019, FR-031). */
/*
 * The gateway injects this as the FIRST script of every html and react
 * artifact it serves in the locked frame (artifacts_store/frame.py), from its
 * own copy: an artifact cannot omit or alter it. It is not a security
 * boundary against the artifact's own code (which runs in the same realm and
 * may do anything this script does); the boundary is the frame: an opaque
 * origin (sandbox="allow-scripts" and the CSP's sandbox directive), no
 * network (connect-src 'none' and every other fetch directive 'none' or
 * data:), no navigation, no popups, no forms, no nested frames. What it adds:
 * - removes the WebRTC constructors (CSP does not govern WebRTC) and refuses
 *   every frame element, by DOM call or by HTML string, so no realm without
 *   this removal can be had (ported from the Apps shim, Spec 011 FR-018);
 * - gives localStorage and sessionStorage as in-memory stores (an opaque
 *   origin has none; nothing persists, nothing is shared between artifacts);
 * - applies the host's theme (class "dark", data-theme, color-scheme and the
 *   Graphite tokens as CSS variables) from the URL fragment, then from the
 *   host's `theme` messages;
 * - says hello to the host with the per-view nonce from the fragment, takes
 *   ONE port (init, from window.parent only) and sends only `ready`,
 *   `size {height}` and `open {url}` (link clicks) over it.
 * It carries no token, no data and no bridge: there is nothing to steal.
 */
(function () {
  "use strict";
  var w = window;
  var d = document;

  var RTC = [
    "RTCPeerConnection", "webkitRTCPeerConnection", "RTCDataChannel", "RTCSessionDescription",
    "RTCIceCandidate", "RTCRtpSender", "RTCRtpReceiver", "RTCRtpTransceiver", "RTCDtlsTransport",
    "RTCIceTransport", "RTCSctpTransport", "RTCCertificate", "RTCEncodedAudioFrame",
    "RTCEncodedVideoFrame", "RTCDTMFSender", "RTCStatsReport", "RTCTrackEvent",
    "RTCPeerConnectionIceEvent", "RTCDataChannelEvent", "RTCError", "RTCErrorEvent"
  ];
  function lock(obj, name, value) {
    if (!obj) return;
    try {
      Object.defineProperty(obj, name, { value: value, writable: false, configurable: false, enumerable: false });
    } catch (_e) {
      try { delete obj[name]; } catch (_e2) { /* nothing more to do */ }
    }
  }
  for (var r = 0; r < RTC.length; r++) lock(w, RTC[r], undefined);

  // No other realm: a frame of any kind would be a fresh realm with WebRTC.
  var FRAME_TAGS = { iframe: 1, frame: 1, frameset: 1, object: 1, embed: 1, portal: 1, fencedframe: 1 };
  var FRAME_SELECTOR = "iframe,frame,frameset,object,embed,portal,fencedframe";
  var FRAME_HTML = /<\s*\/?\s*(iframe|frame|frameset|object|embed|portal|fencedframe)(?![a-z0-9-])/i;
  function refuseFrame() {
    throw new DOMException("Artifacts cannot create frames.", "NotSupportedError");
  }
  function checkHtml(args) {
    for (var i = 0; i < args.length; i++) {
      if (args[i] != null && FRAME_HTML.test(String(args[i]))) refuseFrame();
    }
  }
  // Each HTML argument is turned into a string ONCE; that same string is
  // checked and passed on (an object whose toString answers differently on
  // each call cannot pass the check with one value and write another).
  function once(v) { return v == null ? "" : String(v); }
  function guardMethod(obj, name, at) {
    var f = obj && obj[name];
    if (typeof f !== "function") return;
    lock(obj, name, function () {
      var args = Array.prototype.slice.call(arguments);
      for (var i = 0; i < args.length; i++) {
        if (at === -1 || i === at) args[i] = once(args[i]);
      }
      checkHtml(at === -1 ? args : [args[at]]);
      return f.apply(this, args);
    });
  }
  function guardSetter(proto, name) {
    var desc = proto && Object.getOwnPropertyDescriptor(proto, name);
    if (!desc || !desc.set) return;
    try {
      Object.defineProperty(proto, name, {
        get: desc.get,
        set: function (v) { var t = once(v); checkHtml([t]); desc.set.call(this, t); },
        enumerable: desc.enumerable,
        configurable: false
      });
    } catch (_e) { /* already locked */ }
  }
  var DocProto = w.Document && w.Document.prototype;
  if (DocProto) {
    var createElement = DocProto.createElement;
    var createElementNS = DocProto.createElementNS;
    lock(DocProto, "createElement", function (name) {
      if (FRAME_TAGS[String(name).toLowerCase()]) refuseFrame();
      return createElement.apply(this, arguments);
    });
    lock(DocProto, "createElementNS", function (_ns, qname) {
      if (FRAME_TAGS[String(qname).split(":").pop().toLowerCase()]) refuseFrame();
      return createElementNS.apply(this, arguments);
    });
    guardMethod(DocProto, "write", -1);
    guardMethod(DocProto, "writeln", -1);
  }
  var ElProto = w.Element && w.Element.prototype;
  guardSetter(ElProto, "innerHTML");
  guardSetter(ElProto, "outerHTML");
  guardMethod(ElProto, "insertAdjacentHTML", 1);
  guardMethod(ElProto, "setHTMLUnsafe", 0);
  guardSetter(w.ShadowRoot && w.ShadowRoot.prototype, "innerHTML");
  guardMethod(w.ShadowRoot && w.ShadowRoot.prototype, "setHTMLUnsafe", 0);
  guardMethod(w.Range && w.Range.prototype, "createContextualFragment", 0);
  guardMethod(w.DOMParser && w.DOMParser.prototype, "parseFromString", 0);
  guardMethod(w.Document, "parseHTMLUnsafe", 0);
  lock(w, "XSLTProcessor", undefined);
  // srcdoc in any form is refused (a frame cannot be had anyway; this stops
  // the attribute on whatever element carries it).
  var IFrameProto = w.HTMLIFrameElement && w.HTMLIFrameElement.prototype;
  if (IFrameProto) {
    try { Object.defineProperty(IFrameProto, "srcdoc", { get: function () { return ""; }, set: refuseFrame, configurable: false }); } catch (_e) { /* locked */ }
  }
  ["setAttribute", "setAttributeNS", "toggleAttribute"].forEach(function (name) {
    var f = ElProto && ElProto[name];
    if (typeof f !== "function") return;
    lock(ElProto, name, function () {
      var attr = name === "setAttributeNS" ? arguments[1] : arguments[0];
      if (String(attr).split(":").pop().toLowerCase() === "srcdoc") refuseFrame();
      return f.apply(this, arguments);
    });
  });
  var observer = null;
  try {
    observer = new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var added = records[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          var node = added[j];
          if (!node || node.nodeType !== 1) continue;
          if (FRAME_TAGS[String(node.localName).toLowerCase()]) { node.remove(); continue; }
          var inner = node.querySelectorAll ? node.querySelectorAll(FRAME_SELECTOR) : [];
          for (var k = 0; k < inner.length; k++) inner[k].remove();
        }
      }
    });
    observer.observe(d, { childList: true, subtree: true });
  } catch (_e) { /* the guards above stand */ }
  // Shadow trees are not in the document's subtree: every shadow root made
  // here is observed the same way (and closed ones are refused nothing
  // else: the HTML guards above hold inside them too).
  var attachShadow = ElProto && ElProto.attachShadow;
  if (typeof attachShadow === "function") {
    lock(ElProto, "attachShadow", function () {
      var root = attachShadow.apply(this, arguments);
      try { if (observer) observer.observe(root, { childList: true, subtree: true }); } catch (_e) { /* the guards stand */ }
      return root;
    });
  }

  // In-memory storage: an opaque origin has none, and nothing may persist.
  function memoryStorage() {
    var data = Object.create(null);
    var api = {
      getItem: function (k) { k = String(k); return k in data ? data[k] : null; },
      setItem: function (k, v) { data[String(k)] = String(v); },
      removeItem: function (k) { delete data[String(k)]; },
      clear: function () { data = Object.create(null); },
      key: function (i) { var ks = Object.keys(data); return i >= 0 && i < ks.length ? ks[i] : null; }
    };
    Object.defineProperty(api, "length", { get: function () { return Object.keys(data).length; } });
    return api;
  }
  var stores = { localStorage: memoryStorage(), sessionStorage: memoryStorage() };
  for (var s in stores) {
    try {
      Object.defineProperty(w, s, { value: stores[s], writable: false, configurable: false });
    } catch (_e) { /* left as the browser has it (it throws in an opaque origin) */ }
  }

  // The theme: from the fragment first (the probe and the first paint), then the host.
  var HASH = String((w.location && w.location.hash) || "");
  var NONCE = (/(?:^#|&)n=([A-Za-z0-9_-]{16,64})(?:&|$)/.exec(HASH) || [])[1];
  var START_THEME = (/(?:^#|&)t=(light|dark)(?:&|$)/.exec(HASH) || [])[1] || "light";
  var TOKENS = {
    light: { "--background": "#f7f7f8", "--foreground": "#17181b", "--card": "#ffffff", "--card-foreground": "#17181b", "--primary": "#3355d6", "--primary-foreground": "#ffffff", "--muted": "#f1f2f4", "--muted-foreground": "#5a606b", "--accent": "#f1f2f4", "--accent-foreground": "#17181b", "--destructive": "#b3261e", "--border": "#dddfe3", "--ring": "#3355d6" },
    dark: { "--background": "#121316", "--foreground": "#ecedef", "--card": "#1c1e23", "--card-foreground": "#ecedef", "--primary": "#8fa8ff", "--primary-foreground": "#121316", "--muted": "#24272d", "--muted-foreground": "#9ea3ad", "--accent": "#24272d", "--accent-foreground": "#ecedef", "--destructive": "#ff8a80", "--border": "#2e3138", "--ring": "#8fa8ff" }
  };
  var VAR_NAME = /^--[a-z0-9-]{1,48}$/;
  var VAR_VALUE = /^[#a-zA-Z0-9 .,%()\/-]{1,64}$/;
  var themeListeners = [];
  function applyTheme(theme, vars) {
    if (theme !== "light" && theme !== "dark") return;
    var root = d.documentElement;
    if (!root) return;
    root.classList.toggle("dark", theme === "dark");
    root.setAttribute("data-theme", theme);
    root.style.colorScheme = theme;
    var all = TOKENS[theme];
    for (var name in all) root.style.setProperty(name, all[name]);
    if (vars && typeof vars === "object") {
      var count = 0;
      for (var key in vars) {
        if (++count > 64) break;
        var value = vars[key];
        if (VAR_NAME.test(key) && typeof value === "string" && VAR_VALUE.test(value)) root.style.setProperty(key, value);
      }
    }
    for (var i = 0; i < themeListeners.length; i++) {
      try { themeListeners[i](theme); } catch (_e) { /* the artifact's own error */ }
    }
  }
  applyTheme(START_THEME, null);
  try {
    Object.defineProperty(w, "omniArtifact", {
      value: Object.freeze({
        onTheme: function (fn) { if (typeof fn === "function") themeListeners.push(fn); },
        get theme() { return d.documentElement && d.documentElement.getAttribute("data-theme"); }
      }),
      writable: false,
      configurable: false
    });
  } catch (_e) { /* defined already */ }

  // The port: one, from the parent, once.
  var port = null;
  var lastHeight = -1;
  var MIN = 120;
  var MAX = 1200;
  function send(msg) {
    if (port) {
      try { port.postMessage(msg); } catch (_e) { /* the host went away */ }
    }
  }
  function measure() {
    var root = d.documentElement;
    var body = d.body;
    var h = Math.max(root ? root.scrollHeight : 0, body ? body.scrollHeight : 0);
    h = Math.max(MIN, Math.min(MAX, Math.ceil(h)));
    if (h !== lastHeight) {
      lastHeight = h;
      send({ v: 1, type: "size", height: h });
    }
  }
  var pending = false;
  function schedule() {
    if (pending) return;
    pending = true;
    setTimeout(function () { pending = false; measure(); }, 100);
  }
  function onInit(event) {
    if (port || event.source !== w.parent) return;
    var data = event.data;
    if (!data || data.v !== 1 || data.type !== "init" || !event.ports || event.ports.length !== 1) return;
    if (typeof event.stopImmediatePropagation === "function") event.stopImmediatePropagation();
    w.removeEventListener("message", onInit, true);
    port = event.ports[0];
    port.onmessage = function (e) {
      var m = e.data;
      if (m && m.v === 1 && m.type === "theme") applyTheme(m.theme, m.vars);
    };
    applyTheme(data.theme, data.vars);
    send({ v: 1, type: "ready" });
    lastHeight = -1;
    measure();
    try { new ResizeObserver(schedule).observe(d.documentElement); } catch (_e) { setInterval(measure, 1000); }
  }
  w.addEventListener("message", onInit, true);

  // Links: the frame cannot navigate; https links go to the host, which asks first.
  d.addEventListener("click", function (event) {
    var node = event.target;
    while (node && node.nodeType === 1 && node.tagName !== "A") node = node.parentNode;
    if (!node || node.nodeType !== 1 || !node.getAttribute) return;
    var href = node.getAttribute("href");
    if (!href || href.charAt(0) === "#") return;
    event.preventDefault();
    if (/^https:\/\//i.test(href) && href.length <= 2048) send({ v: 1, type: "open", url: href });
  }, true);

  if (w.parent !== w && NONCE) {
    try { w.parent.postMessage({ v: 1, type: "hello", nonce: NONCE }, "*"); } catch (_e) { /* the host tears the frame down */ }
  }
})();
