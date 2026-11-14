// A small app on the kit: three tiles, each with the four honest states.
const TILES = [
  { source: "calendar", title: "Calendar", empty: "Nothing today", render: renderCalendar },
  { source: "gh_review", title: "Waiting on your review", empty: "No PRs waiting on you", render: renderPrs },
  { source: "inbox", title: "Inbox pulse", empty: "Nothing today", render: renderInbox },
];

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function svg(tag, attrs) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
  return node;
}

function time(iso) {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toISOString().slice(11, 16);
}

function renderCalendar(body, data) {
  const items = data.items || [];
  const timed = items.filter((i) => !i.all_day && i.start && i.end);
  const chart = svg("svg", { viewBox: "0 0 240 48", class: "omni-chart load-chart", role: "img", "aria-label": "Meetings across the day" });
  chart.appendChild(svg("line", { x1: 0, y1: 30, x2: 240, y2: 30, class: "omni-axis" }));
  for (const item of timed) {
    const s = new Date(item.start), e = new Date(item.end);
    const x0 = ((s.getUTCHours() + s.getUTCMinutes() / 60 - 8) / 10) * 240;
    const x1 = ((e.getUTCHours() + e.getUTCMinutes() / 60 - 8) / 10) * 240;
    chart.appendChild(svg("rect", { x: Math.max(0, x0), y: 18, width: Math.max(2, Math.min(240, x1) - Math.max(0, x0)), height: 10, rx: 2, class: "omni-series" }));
  }
  for (const [h, x] of [["08", 0], ["13", 120], ["18", 240]]) {
    const t = svg("text", { x: Math.min(Math.max(x, 8), 228), y: 46, "text-anchor": "middle" });
    t.textContent = h;
    chart.appendChild(t);
  }
  body.appendChild(chart);
  const list = el("ul", "omni-list");
  for (const item of items) {
    const li = el("li");
    li.appendChild(el("span", "omni-list-main", item.title || "(no title)"));
    li.appendChild(el("span", "omni-list-meta", item.all_day ? "all day" : time(item.start)));
    list.appendChild(li);
  }
  body.appendChild(list);
}

function renderPrs(body, data) {
  const list = el("ul", "omni-list");
  for (const item of data.items || []) {
    const li = el("li");
    const a = el("a", "omni-list-main", item.title || "");
    a.href = item.link || "#";
    li.appendChild(a);
    li.appendChild(el("span", "omni-list-meta", `${item.repo || ""} #${item.number ?? ""}`));
    list.appendChild(li);
  }
  body.appendChild(list);
}

function renderInbox(body, data) {
  const kpis = el("div", "omni-kpis");
  const kpi = el("div", "omni-kpi");
  kpi.appendChild(el("span", "omni-kpi-value", String(data.count ?? 0)));
  kpi.appendChild(el("span", "omni-kpi-label", "probably need a reply (unread in Primary, 3 days)"));
  kpis.appendChild(kpi);
  body.appendChild(kpis);
  const list = el("ul", "omni-list");
  for (const item of (data.items || []).slice(0, 4)) {
    const li = el("li");
    li.appendChild(el("span", "omni-list-main", item.subject || ""));
    list.appendChild(li);
  }
  body.appendChild(list);
}

function renderTile(tile, node, result) {
  node.replaceChildren();
  const head = el("div", "omni-tile-head");
  head.appendChild(el("h2", "omni-tile-title", tile.title));
  const words = omni.describe(result);
  const body = el("div");
  if (result.state === "fresh") {
    head.appendChild(el("span", "omni-tile-meta", words.label));
    tile.render(body, result.data || {});
    if (result.stale) body.appendChild(el("p", "omni-stale", "May be out of date"));
  } else {
    const state = el("div", "omni-state" + (result.state === "failed" ? " omni-state-failed" : ""));
    state.appendChild(el("span", "omni-state-label", result.state === "empty" ? tile.empty : words.label));
    state.appendChild(el("span", "omni-state-detail", words.detail));
    if (result.state === "not_connected") {
      const b = el("button", "omni-button omni-button-primary", "Connect");
      b.type = "button";
      b.addEventListener("click", () => omni.connect(tile.source));
      state.appendChild(b);
    }
    body.appendChild(state);
  }
  node.appendChild(head);
  node.appendChild(body);
}

const grid = document.getElementById("grid");
for (const tile of TILES) {
  const node = el("section", "omni-tile");
  node.appendChild(el("span", "omni-skeleton"));
  grid.appendChild(node);
  omni.data(tile.source).then((r) => renderTile(tile, node, r), () => renderTile(tile, node, { state: "failed", reason: "No answer", data: null }));
}
omni.onUpdate((name, result) => {
  const at = TILES.findIndex((t) => t.source === name);
  if (at !== -1) renderTile(TILES[at], grid.children[at], result);
});
