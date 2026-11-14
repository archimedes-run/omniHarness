/**
 * Spec 011 FR-018 (WebRTC is not governed by CSP): an app that looks for a
 * JavaScript realm the shim never ran in, and uses WebRTC from there to send
 * STUN packets to a UDP listener the spec owns.
 *
 * The script copies ITS OWN text into a child document (srcdoc), so the
 * child's script matches the app's allowed hash. In the child (its parent
 * is not the top page) it only tries WebRTC. In the app it tries the vectors named.
 *
 * Vectors:
 * - top: WebRTC in the app's own realm (the shim removes it).
 * - srcdoc-create: createElement("iframe") + srcdoc = own script.
 * - srcdoc-innerhtml: an <iframe srcdoc=...> written with innerHTML.
 * - srcdoc-adjacent: the same with insertAdjacentHTML.
 * - srcdoc-attribute: setAttribute("srcdoc", ...).
 * - blank-create: createElement("iframe") with no src, then WebRTC from its
 *   initial about:blank realm, reached through window[n].
 * - blank-innerhtml: the same frame written with innerHTML.
 * - xslt: an <iframe> made by XSLTProcessor (no createElement, no HTML string).
 *
 * `hello`: served without the shim, the script says the shim's hello itself.
 */
export function rtcScript(
  udp: string,
  vectors: string[],
  { hello = false } = {},
): string {
  return `
(function(){
  var U = ${JSON.stringify(udp)};
  var V = ${JSON.stringify(vectors)};
  var me = document.currentScript ? document.currentScript.textContent : "";
  // In the child, the parent is the app frame, not the top page.
  var child = window.parent !== window.top;
  function rtc(w) {
    var PC = w.RTCPeerConnection || w.webkitRTCPeerConnection;
    if (!PC) return "no-rtc";
    var pc = new PC({ iceServers: [{ urls: "stun:" + U }] });
    pc.createDataChannel("x");
    pc.createOffer().then(function (o) { return pc.setLocalDescription(o); });
    return "started";
  }
  if (child) { try { rtc(window); } catch (e) {} return; }
  // Served without the shim: say its hello, so the host keeps the frame.
  if (${hello ? "true" : "false"}) {
    var n = /^#omni-nonce=([A-Za-z0-9_-]{16,64})$/.exec(location.hash);
    if (n) parent.postMessage({ v: 1, type: "hello", nonce: n[1] }, "*");
  }
  var R = window.__rtc = {};
  function attempt(name, fn) {
    if (V.indexOf(name) === -1) return;
    try { R[name] = String(fn()); } catch (e) { R[name] = "error: " + e; }
  }
  var S = "<scr" + "ipt>" + me + "</scr" + "ipt>";
  function esc(t) { return t.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function lastRealm() { return window[window.length - 1]; }
  attempt("top", function () { return rtc(window); });
  attempt("srcdoc-create", function () {
    var f = document.createElement("iframe"); f.srcdoc = S; document.body.appendChild(f); return "made";
  });
  attempt("srcdoc-innerhtml", function () {
    var d = document.createElement("div"); d.innerHTML = '<iframe srcdoc="' + esc(S) + '"></iframe>'; document.body.appendChild(d); return "made";
  });
  attempt("srcdoc-adjacent", function () {
    document.body.insertAdjacentHTML("beforeend", '<iframe srcdoc="' + esc(S) + '"></iframe>'); return "made";
  });
  attempt("srcdoc-attribute", function () {
    var f = document.createElement("iframe"); f.setAttribute("srcdoc", S); document.body.appendChild(f); return "made";
  });
  attempt("blank-create", function () {
    var f = document.createElement("iframe"); document.body.appendChild(f); return rtc(lastRealm());
  });
  attempt("blank-innerhtml", function () {
    var d = document.createElement("div"); d.innerHTML = "<iframe></iframe>"; document.body.appendChild(d); return rtc(lastRealm());
  });
  attempt("xslt", function () {
    var X = window.XSLTProcessor; if (!X) return "no-xslt";
    var ns = "http://www.w3.org/1999/XSL/Transform";
    var xsl = document.implementation.createDocument(ns, "xsl:stylesheet", null);
    var root = xsl.documentElement; root.setAttribute("version", "1.0");
    var t = xsl.createElementNS(ns, "xsl:template"); t.setAttribute("match", "/");
    var out = xsl.createElementNS("http://www.w3.org/1999/xhtml", "iframe");
    t.appendChild(out); root.appendChild(t);
    var p = new X(); p.importStylesheet(xsl);
    var frag = p.transformToFragment(document.implementation.createDocument(null, "x", null), document);
    document.body.appendChild(frag);
    return rtc(lastRealm());
  });
  setTimeout(function () { document.body.setAttribute("data-rtc-done", "1"); }, 500);
})();
`;
}
