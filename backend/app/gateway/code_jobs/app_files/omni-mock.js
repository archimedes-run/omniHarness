/*
 * The MOCK platform shim for an app's mock build (Spec 011 FR-025, FR-026).
 * Written by the gateway; never part of a registered app. The gateway puts it,
 * with the kit's sample data (`__OMNI_MOCK__`), as the first script of the
 * built page, and the system's checks load that page once per theme and
 * state. It has the real shim's `window.omni` API (omni.d.ts) and the same
 * tile words (`ago`, `describe`: a test keeps them identical), and answers
 * every source from the sample data instead of the host page:
 *
 *   ?state=fresh|empty|not_connected|failed   every source in that state
 *   ?theme=light|dark                          <html> gets .dark for dark
 *   ?state.calendar=failed                     one source only (for trying)
 */
(function () {
  "use strict";
  var w = window;
  var MOCK = w.__OMNI_MOCK__ || { reference: null, reason: "", sources: {} };
  var STATES = ["fresh", "empty", "not_connected", "failed"];
  var query = {};
  try {
    var pairs = (w.location.search || "").replace(/^\?/, "").split("&");
    for (var i = 0; i < pairs.length; i++) {
      if (!pairs[i]) continue;
      var at = pairs[i].indexOf("=");
      var key = decodeURIComponent(at < 0 ? pairs[i] : pairs[i].slice(0, at));
      query[key] = at < 0 ? "" : decodeURIComponent(pairs[i].slice(at + 1));
    }
  } catch (_e) {
    query = {};
  }
  function stateOf(source) {
    var own = query["state." + source];
    if (STATES.indexOf(own) !== -1) return own;
    return STATES.indexOf(query.state) !== -1 ? query.state : "fresh";
  }
  var theme = query.theme === "dark" ? "dark" : "light";
  var MINUTE = 60000;
  var DAY = 86400000;

  // Sample times are written for a reference day; they move to today,
  // keeping their time of day.
  var shiftDays = 0;
  if (MOCK.reference) {
    var ref = new Date(MOCK.reference).getTime();
    if (!isNaN(ref)) {
      var today = new Date();
      today.setUTCHours(0, 0, 0, 0);
      var refDay = new Date(ref);
      refDay.setUTCHours(0, 0, 0, 0);
      shiftDays = Math.round((today.getTime() - refDay.getTime()) / DAY);
    }
  }
  var STAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;
  var DATE = /^\d{4}-\d{2}-\d{2}$/;
  function moved(value) {
    if (typeof value === "string") {
      if (STAMP.test(value)) {
        var t = new Date(value).getTime();
        return isNaN(t) ? value : new Date(t + shiftDays * DAY).toISOString();
      }
      if (DATE.test(value)) {
        var d = new Date(value + "T00:00:00Z").getTime();
        return isNaN(d)
          ? value
          : new Date(d + shiftDays * DAY).toISOString().slice(0, 10);
      }
      return value;
    }
    if (Array.isArray(value)) return value.map(moved);
    if (value && typeof value === "object") {
      var out = {};
      for (var k in value) {
        if (Object.prototype.hasOwnProperty.call(value, k))
          out[k] = moved(value[k]);
      }
      return out;
    }
    return value;
  }

  function result(source) {
    var entry = MOCK.sources[source];
    var state = stateOf(source);
    var now = Date.now();
    if (state === "fresh") {
      return {
        source: source,
        state: state,
        data: moved(entry.fresh),
        fetched_at: new Date(now - 4 * MINUTE).toISOString(),
        stale: false,
        reason: null,
      };
    }
    if (state === "empty") {
      return {
        source: source,
        state: state,
        data: JSON.parse(JSON.stringify(entry.empty)),
        fetched_at: new Date(now - 4 * MINUTE).toISOString(),
        stale: false,
        reason: null,
      };
    }
    if (state === "not_connected") {
      return {
        source: source,
        state: state,
        data: null,
        fetched_at: null,
        stale: false,
        reason: null,
      };
    }
    return {
      source: source,
      state: "failed",
      data: null,
      fetched_at: null,
      stale: false,
      reason: MOCK.reason || "The source could not be read",
    };
  }

  var themeListeners = [];
  var updateListeners = [];
  var errorListeners = [];
  function subscribe(list, fn) {
    if (typeof fn !== "function") return function () {};
    list.push(fn);
    return function () {
      var at = list.indexOf(fn);
      if (at !== -1) list.splice(at, 1);
    };
  }
  function applyTheme(next) {
    var root = document.documentElement;
    if (root) {
      if (next === "dark") root.classList.add("dark");
      else root.classList.remove("dark");
      root.style.colorScheme = next;
    }
  }
  applyTheme(theme);

  function answer(source) {
    return new Promise(function (resolve, reject) {
      // A short wait, so the app's first-answer placeholder is exercised.
      setTimeout(function () {
        if (!Object.prototype.hasOwnProperty.call(MOCK.sources, source)) {
          for (var i = 0; i < errorListeners.length; i++) {
            try {
              errorListeners[i]("source_not_approved");
            } catch (_e) {
              /* the app's listener */
            }
          }
          reject(new Error("source_not_approved"));
          return;
        }
        resolve(result(source));
      }, 30);
    });
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
    ready: Promise.resolve({ app: "mock", version: 0, theme: theme }),
    data: answer,
    refresh: answer,
    open: function (url) {
      return typeof url === "string" && url.length > 0 && url.length <= 2048;
    },
    connect: function (source) {
      return Object.prototype.hasOwnProperty.call(MOCK.sources, source);
    },
    onTheme: function (fn) {
      var off = subscribe(themeListeners, fn);
      if (typeof fn === "function") fn(theme);
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

  // As in the real shim: links go through omni.open; the page never navigates.
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
})();
