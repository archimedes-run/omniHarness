/*
 * OmniHarness platform shim (Spec 011 FR-018, FR-023). The source of
 * omni-shim.js: scripts/build-app-shim.mjs replaces the two markers below
 * with protocol.schema.json and validate.js, the same schema and the same
 * function the host page checks with. Edit this file, then run
 * `node scripts/build-app-shim.mjs`; a unit test fails if the two drift.
 *
 * It runs first in every app, before app code, as an inline script:
 * - removes the WebRTC constructors (CSP does not govern WebRTC);
 * - accepts `init` once, only from window.parent, only with one port; after
 *   that it listens to that port and nothing else;
 * - validates every host message against the schema; nothing is evaluated,
 *   data reaches app code as the parsed JSON it already is;
 * - validates its own outgoing messages the same way;
 * - sends link clicks through the host (`open`), since the frame cannot
 *   navigate anywhere itself;
 * - exposes `window.omni` (see omni.d.ts), frozen.
 */
(function () {
  "use strict";
  var w = window;

  // FR-018: no WebRTC. Defined as undefined and locked, so app code cannot
  // put them back.
  var RTC = [
    "RTCPeerConnection",
    "webkitRTCPeerConnection",
    "RTCDataChannel",
    "RTCSessionDescription",
    "RTCIceCandidate",
    "RTCRtpSender",
    "RTCRtpReceiver",
    "RTCRtpTransceiver",
    "RTCDtlsTransport",
    "RTCIceTransport",
    "RTCSctpTransport",
    "RTCCertificate",
    "RTCEncodedAudioFrame",
    "RTCEncodedVideoFrame",
    "RTCDTMFSender",
    "RTCStatsReport",
    "RTCTrackEvent",
    "RTCPeerConnectionIceEvent",
    "RTCDataChannelEvent",
    "RTCError",
    "RTCErrorEvent",
  ];
  for (var r = 0; r < RTC.length; r++) {
    try {
      Object.defineProperty(w, RTC[r], {
        value: undefined,
        writable: false,
        configurable: false,
        enumerable: false,
      });
    } catch (_e) {
      try {
        delete w[RTC[r]];
      } catch (_e2) {
        /* nothing more to do */
      }
    }
  }

  var SCHEMA = /*@@PROTOCOL_SCHEMA@@*/ null;
  var validateProtocolMessage = /*@@VALIDATE@@*/ null;

  var port = null;
  var info = null;
  var theme = null;
  var seq = 0;
  var pending = {};
  var queue = [];
  var themeListeners = [];
  var updateListeners = [];
  var errorListeners = [];
  var readyResolve;
  var ready = new Promise(function (resolve) {
    readyResolve = resolve;
  });

  function callAll(list, args) {
    for (var i = 0; i < list.length; i++) {
      try {
        list[i].apply(null, args);
      } catch (err) {
        setTimeout(function () {
          throw err;
        });
      }
    }
  }

  function applyTheme(next) {
    theme = next;
    var root = document.documentElement;
    if (root) {
      if (next === "dark") root.classList.add("dark");
      else root.classList.remove("dark");
      root.style.colorScheme = next;
    }
    callAll(themeListeners, [next]);
  }

  function send(message) {
    var verdict = validateProtocolMessage(SCHEMA, "frame_to_host", message);
    if (!verdict.ok) return verdict.reason;
    if (!port) {
      queue.push(message);
      return null;
    }
    port.postMessage(message);
    return null;
  }

  function resultOf(m) {
    return {
      source: m.source,
      state: m.state,
      data: m.data,
      fetched_at: m.fetched_at,
      stale: m.stale,
      reason: m.reason === undefined ? null : m.reason,
    };
  }

  function onPortMessage(event) {
    var m = event.data;
    if (event.ports && event.ports.length) return;
    var verdict = validateProtocolMessage(SCHEMA, "host_to_frame", m);
    if (!verdict.ok) return;
    if (m.type === "init") return; // once, on the window, only
    if (m.type === "theme") {
      applyTheme(m.theme);
      return;
    }
    if (m.type === "result") {
      var waiter = pending[m.id];
      if (!waiter || waiter.source !== m.source) return;
      delete pending[m.id];
      waiter.resolve(resultOf(m));
      return;
    }
    if (m.type === "update") {
      callAll(updateListeners, [m.source, resultOf(m)]);
      return;
    }
    if (m.type === "error") {
      if (m.id && pending[m.id]) {
        var failed = pending[m.id];
        delete pending[m.id];
        failed.reject(new Error(m.reason));
      }
      callAll(errorListeners, [m.reason]);
    }
  }

  function onWindowMessage(event) {
    if (port) return; // the handshake happens once
    if (event.source !== w.parent || w.parent === w) return;
    if (!event.ports || event.ports.length !== 1) return;
    var m = event.data;
    var verdict = validateProtocolMessage(SCHEMA, "host_to_frame", m);
    if (!verdict.ok || m.type !== "init") return;
    port = event.ports[0];
    port.onmessage = onPortMessage;
    w.removeEventListener("message", onWindowMessage);
    info = { app: m.app, version: m.version, theme: m.theme };
    applyTheme(m.theme);
    var waiting = queue;
    queue = [];
    for (var i = 0; i < waiting.length; i++) port.postMessage(waiting[i]);
    readyResolve(info);
  }
  w.addEventListener("message", onWindowMessage);

  function request(type, source) {
    return new Promise(function (resolve, reject) {
      seq += 1;
      var id = "r" + seq;
      pending[id] = { source: source, resolve: resolve, reject: reject };
      var refused = send({ v: 1, type: type, id: id, source: source });
      if (refused) {
        delete pending[id];
        reject(new Error(refused));
      }
    });
  }

  function subscribe(list, fn) {
    if (typeof fn !== "function") return function () {};
    list.push(fn);
    return function () {
      var at = list.indexOf(fn);
      if (at !== -1) list.splice(at, 1);
    };
  }

  /** "just now", "4 min ago", "3 h ago", "2 days ago". */
  function ago(iso) {
    if (!iso) return "";
    var t = new Date(iso).getTime();
    if (isNaN(t)) return "";
    var s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 45) return "just now";
    var min = Math.round(s / 60);
    if (min < 60) return min + " min ago";
    var h = Math.round(min / 60);
    if (h < 36) return h + " h ago";
    var d = Math.round(h / 24);
    return d + (d === 1 ? " day ago" : " days ago");
  }

  /** The standard words for a tile in each state (shim/README.md). */
  function describe(result) {
    if (!result) return { label: "Can't tell", detail: "No answer yet" };
    switch (result.state) {
      case "fresh":
        return {
          label: "updated " + ago(result.fetched_at),
          detail: result.stale ? "May be out of date" : "",
        };
      case "empty":
        return {
          label: "Nothing today",
          detail: "updated " + ago(result.fetched_at),
        };
      case "not_connected":
        return { label: "Not connected", detail: "Connect it to show this" };
      default:
        return {
          label: "Can't tell",
          detail: result.reason || "The source could not be read",
        };
    }
  }

  var omni = {
    ready: ready,
    data: function (source) {
      return ready.then(function () {
        return request("data", source);
      });
    },
    refresh: function (source) {
      return ready.then(function () {
        return request("refresh", source);
      });
    },
    open: function (url) {
      return send({ v: 1, type: "open", url: String(url) }) === null;
    },
    connect: function (source) {
      return send({ v: 1, type: "connect", source: source }) === null;
    },
    onTheme: function (fn) {
      var off = subscribe(themeListeners, fn);
      if (theme && typeof fn === "function") fn(theme);
      return off;
    },
    onUpdate: function (fn) {
      return subscribe(updateListeners, fn);
    },
    onError: function (fn) {
      return subscribe(errorListeners, fn);
    },
    get theme() {
      return theme;
    },
    ago: ago,
    describe: describe,
  };
  Object.freeze(omni);
  Object.defineProperty(w, "omni", {
    value: omni,
    writable: false,
    configurable: false,
    enumerable: true,
  });

  // Links go through the host: the frame cannot navigate anywhere itself.
  document.addEventListener(
    "click",
    function (event) {
      var node = event.target;
      while (node && node.nodeType === 1 && node.tagName !== "A") {
        node = node.parentNode;
      }
      if (!node || node.nodeType !== 1 || !node.getAttribute) return;
      var href = node.getAttribute("href");
      if (!href || href.charAt(0) === "#") return;
      event.preventDefault();
      omni.open(href);
    },
    true,
  );

  // Opened as a page of its own (not from OmniHarness): say so.
  if (w.parent === w) {
    var notice = function () {
      document.body.textContent = "Open this app from OmniHarness.";
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", notice);
    } else {
      notice();
    }
  } else {
    try {
      w.parent.postMessage({ v: 1, type: "ready" }, "*");
    } catch (_e) {
      /* the host does not need it */
    }
  }
})();
