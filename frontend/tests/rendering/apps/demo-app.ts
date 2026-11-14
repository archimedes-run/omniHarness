/**
 * Spec 011: a tiny built-in demo app for the rendering specs. MOCK DATA ONLY
 * (the fake bridge's), no real accounts. It is what a kit-built app looks
 * like: the shim first, then one inline script that asks for each source by
 * name and renders every tile in all four states with the standard words
 * (omni.describe), Graphite tokens in both themes, responsive from 360 px.
 *
 * For the specs it also records every host → frame message (window.__omniLog,
 * read through Playwright, which can look into the opaque frame) and the time
 * the last tile rendered (window.__renderedAt, epoch ms).
 */

export const DEMO_SOURCES = ["calendar", "gh_review", "inbox", "ledger"];

export const DEMO_STYLE = `
:root{--background:#f7f7f8;--foreground:#17181b;--card:#ffffff;--muted-foreground:#5a606b;--border:#dddfe3;--primary:#3355d6;--primary-foreground:#ffffff;--warning:#8a5300;--destructive:#b3261e;--success:#1e7a4b;color-scheme:light}
.dark{--background:#121316;--foreground:#ecedef;--card:#1c1e23;--muted-foreground:#9ea3ad;--border:#2e3138;--primary:#8fa8ff;--primary-foreground:#121316;--warning:#f2b65a;--destructive:#ff8a80;--success:#6fd3a0;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--background);color:var(--foreground);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{display:grid;gap:14px;padding:16px;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));max-width:1200px;margin:0 auto}
h1{grid-column:1/-1;margin:0;font-size:20px}
.tile{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:14px 16px;min-height:120px;display:flex;flex-direction:column;gap:8px}
.tile h2{margin:0;font-size:15px}
.meta{font-size:12px;color:var(--muted-foreground)}
.meta.warn{color:var(--warning)}
.meta.bad{color:var(--destructive)}
ul{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:6px}
li a{color:var(--foreground);text-decoration:underline;text-underline-offset:2px}
button{align-self:flex-start;min-height:32px;padding:0 12px;border-radius:8px;border:0;background:var(--primary);color:var(--primary-foreground);font:inherit;cursor:pointer}
.big{font-size:28px;font-weight:600}
`;

export const DEMO_BODY = `<main><h1>Today (demo)</h1>${DEMO_SOURCES.map(
  (s) =>
    `<section class="tile" data-tile="${s}" data-state="loading"><h2>${
      {
        calendar: "Calendar",
        gh_review: "Waiting on your review",
        inbox: "Inbox pulse",
        ledger: "Ledger",
      }[s]
    }</h2><p class="meta">Loading</p></section>`,
).join("")}</main>`;

export const DEMO_SCRIPT = `
(function(){
  var SOURCES = ${JSON.stringify(DEMO_SOURCES)};
  window.__omniLog = [];
  window.addEventListener("message", function (e) {
    if (e.ports && e.ports[0]) {
      window.__omniLog.push(e.data);
      e.ports[0].addEventListener("message", function (m) { window.__omniLog.push(m.data); });
    }
  });
  var done = {};
  function el(tag, cls, text){ var n=document.createElement(tag); if(cls) n.className=cls; if(text!=null) n.textContent=text; return n; }
  function render(name, r){
    var tile = document.querySelector('[data-tile="'+name+'"]');
    var title = tile.querySelector("h2");
    tile.textContent = "";
    tile.appendChild(title);
    tile.setAttribute("data-state", r.state);
    var words = omni.describe(r);
    var meta = el("p", "meta" + (r.state === "failed" ? " bad" : r.state === "not_connected" ? " warn" : ""), words.label + (words.detail ? " · " + words.detail : ""));
    tile.appendChild(meta);
    if (r.state === "not_connected") {
      var b = el("button", null, "Connect");
      b.setAttribute("data-connect", name);
      b.addEventListener("click", function(){ omni.connect(name); });
      tile.appendChild(b);
    }
    var data = r.data;
    if (data && typeof data.count === "number") tile.appendChild(el("p", "big", String(data.count)));
    if (data && data.items && data.items.length) {
      var ul = el("ul");
      data.items.slice(0, 5).forEach(function(it){
        var li = el("li");
        var label = it.title || it.subject || it.task || ("#" + it.number);
        if (it.link) { var a = el("a", null, label); a.setAttribute("href", it.link); li.appendChild(a); }
        else li.textContent = label;
        ul.appendChild(li);
      });
      tile.appendChild(ul);
    }
    done[name] = true;
    if (SOURCES.every(function(s){ return done[s]; }) && !window.__renderedAt) {
      window.__renderedAt = performance.timeOrigin + performance.now();
      document.body.setAttribute("data-rendered", "all");
    }
  }
  SOURCES.forEach(function(name){
    omni.data(name).then(function(r){ render(name, r); }, function(err){
      render(name, { state: "failed", data: null, fetched_at: null, stale: false, reason: String(err && err.message || err) });
    });
  });
  omni.onUpdate(function(name, r){ render(name, r); });
})();
`;
