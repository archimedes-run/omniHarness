# ruff: noqa: E501 - fixture pages: long HTML lines
"""Pages for the artifact chart checks (layout_probe.CHART_MEASURE).

GOOD: charts drawn the way the artifact tool description asks (theme
colours, labels wrapped or thinned to fit, nothing outside the svg), in
several configurations, plus the Apps kit's own chart parts (Sparkline,
Timeline) with the kit's real CSS. BAD: one deliberately broken chart per
rule, and the live budget-tracker pattern. ORDINARY: pages with no chart at
all (icons, a logo, a sparkline, a table, a form, a nav row, decorations).
Every page is self-contained: inline script and style only, no network,
elements built with createElement / createElementNS (the frame refuses
innerHTML)."""

from __future__ import annotations

from pathlib import Path

KIT = Path(__file__).resolve().parents[2] / "app" / "gateway" / "code_jobs" / "app_files"

BASE_CSS = (
    "*{box-sizing:border-box}body{margin:0;font:14px/1.4 system-ui,-apple-system,'Segoe UI',sans-serif;background:var(--background);color:var(--foreground)}"
    ".card{background:var(--card);color:var(--card-foreground);border:1px solid var(--border);border-radius:12px;padding:16px;margin:16px}"
    "h2{font-size:16px;margin:0 0 8px}.host{width:100%}"
)


def doc(body: str, *, style: str = "", script: str = "") -> str:
    return f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>t</title><style>{BASE_CSS}{style}</style></head><body>{body}{f'<script>{script}</script>' if script else ''}</body></html>"


#: The pattern the guidance describes, in plain DOM calls: an svg sized to
#: its box in px, marks in var(--primary), labels in var(--muted-foreground)
#: at 11 px+, each x label fitted to its slot (wrapped onto two lines,
#: hyphenated, ellipsised) and thinned when slots get narrow.
LIB = r"""
const NS = 'http://www.w3.org/2000/svg';
function el(tag, attrs, parent) { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
function width(svg, text, size) { const t = el('text', { 'font-size': size, x: 0, y: -100 }, svg); t.textContent = text; const w = t.getComputedTextLength(); t.remove(); return w; }
function fit(svg, text, room, size) {
  if (width(svg, text, size) <= room) return [text];
  const words = text.split(' ');
  if (words.length > 1) {
    const a = words[0], b = words.slice(1).join(' ');
    if (width(svg, a, size) <= room) return [a, clipTo(svg, b, room, size)];
  }
  for (let i = text.length - 1; i > 1; i--) {
    const head = text.slice(0, i) + '-';
    if (width(svg, head, size) <= room) return [head, clipTo(svg, text.slice(i), room, size)];
  }
  return [clipTo(svg, text, room, size)];
}
function clipTo(svg, text, room, size) {
  if (width(svg, text, size) <= room) return text;
  for (let i = text.length - 1; i > 0; i--) { const s = text.slice(0, i) + '…'; if (width(svg, s, size) <= room) return s; }
  return '';
}
function label(svg, x, y, lines, size, anchor) {
  const t = el('text', { x, y, 'text-anchor': anchor || 'middle', 'font-size': size, fill: 'var(--muted-foreground)' }, svg);
  lines.forEach((ln, k) => { const s = el('tspan', { x, dy: k ? '1.2em' : 0 }, t); s.textContent = ln; });
  return t;
}
function frame(host, title, h) {
  host.textContent = '';
  const W = Math.max(120, host.clientWidth);
  const svg = el('svg', { width: W, height: h, viewBox: `0 0 ${W} ${h}`, role: 'img', 'aria-label': title }, host);
  el('title', {}, svg).textContent = title;
  return { svg, W };
}
function grid(svg, x0, x1, y0, ph, max, n) {
  for (let i = 0; i <= n; i++) {
    const y = y0 + ph - (ph * i) / n;
    el('line', { x1: x0, x2: x1, y1: y, y2: y, stroke: 'var(--border)', 'stroke-width': 1 }, svg);
    label(svg, x0 - 6, y + 4, [String(Math.round((max * i) / n))], 11, 'end');
  }
}
function barChart(host, data, o) {
  const draw = () => {
    const H = o.height || 240, size = o.size || 12;
    const { svg, W } = frame(host, o.title, H);
    const pad = { l: 40, r: 8, t: 10, b: 44 };
    const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    const max = Math.max(...data.map((d) => d.value));
    grid(svg, pad.l, W - pad.r, pad.t, ph, max, 4);
    const step = pw / data.length, bw = Math.max(2, step * 0.7);
    const every = Math.max(1, Math.ceil(30 / step));
    data.forEach((d, i) => {
      const h = (ph * d.value) / max, x = pad.l + i * step + (step - bw) / 2;
      el('rect', { x, y: pad.t + ph - h, width: bw, height: h, rx: 3, fill: o.colour || 'var(--primary)' }, svg);
      if (i % every) return;
      label(svg, x + bw / 2, pad.t + ph + 16, fit(svg, d.label, step * every - 4, size), size);
    });
  };
  draw();
  addEventListener('resize', draw);
}
function lineChart(host, data, o) {
  const draw = () => {
    const H = 220;
    const { svg, W } = frame(host, o.title, H);
    const pad = { l: 40, r: 12, t: 10, b: 28 };
    const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    const max = Math.max(...data.map((d) => d.value));
    for (let i = 0; i <= 4; i++) {
      const y = pad.t + ph - (ph * i) / 4;
      el('line', { x1: pad.l, x2: W - pad.r, y1: y, y2: y, stroke: 'var(--border)', 'stroke-dasharray': '3 3' }, svg);
      label(svg, pad.l - 6, y + 4, [String(Math.round((max * i) / 4))], 11, 'end');
    }
    const step = pw / (data.length - 1);
    const pts = data.map((d, i) => [pad.l + i * step, pad.t + ph - (ph * d.value) / max]);
    if (o.area) {
      const defs = el('defs', {}, svg);
      const g = el('linearGradient', { id: 'fade', x1: 0, x2: 0, y1: 0, y2: 1 }, defs);
      el('stop', { offset: '0%', 'stop-color': 'var(--primary)', 'stop-opacity': 0.5 }, g);
      el('stop', { offset: '100%', 'stop-color': 'var(--primary)', 'stop-opacity': 0 }, g);
      el('path', { d: 'M' + pts.map((p) => p.join(',')).join('L') + `L${pts[pts.length - 1][0]},${pad.t + ph}L${pad.l},${pad.t + ph}Z`, fill: 'url(#fade)' }, svg);
    }
    el('path', { d: 'M' + pts.map((p) => p.join(',')).join('L'), fill: 'none', stroke: 'var(--primary)', 'stroke-width': 2 }, svg);
    pts.forEach((p) => el('circle', { cx: p[0], cy: p[1], r: 3.5, fill: 'var(--primary)' }, svg));
    const every = Math.max(1, Math.ceil(34 / step));
    data.forEach((d, i) => { if (i % every === 0) label(svg, pts[i][0], pad.t + ph + 18, [d.label], 11, i === 0 ? 'start' : i === data.length - 1 ? 'end' : 'middle'); });
  };
  draw();
  addEventListener('resize', draw);
}
function hbarChart(host, data, o) {
  const draw = () => {
    const row = 34, H = data.length * row + 8;
    const { svg, W } = frame(host, o.title, H);
    const lw = Math.min(120, W * 0.32), max = Math.max(...data.map((d) => d.value));
    data.forEach((d, i) => {
      const y = 4 + i * row, lines = fit(svg, d.label, lw - 8, 12);
      label(svg, lw - 8, y + (lines.length > 1 ? 12 : 19), lines, 12, 'end');
      const bw = ((W - lw - 48) * d.value) / max;
      el('rect', { x: lw, y: y + 6, width: bw, height: 18, rx: 3, fill: 'var(--primary)' }, svg);
      label(svg, lw + bw + 6, y + 19, ['$' + d.value], 11, 'start');
    });
  };
  draw();
  addEventListener('resize', draw);
}
function donut(host, data, o) {
  const draw = () => {
    host.textContent = '';
    const S = 160, r = 60, c = 2 * Math.PI * r;
    const svg = el('svg', { width: S, height: S, viewBox: `0 0 ${S} ${S}`, role: 'img', 'aria-label': o.title }, host);
    el('title', {}, svg).textContent = o.title;
    el('circle', { cx: 80, cy: 80, r, fill: 'none', stroke: 'var(--muted)', 'stroke-width': 18 }, svg);
    const total = data.reduce((s, d) => s + d.value, 0);
    let at = 0;
    const colours = o.colours || ['var(--primary)', 'var(--foreground)', 'var(--destructive)', 'var(--muted-foreground)'];
    data.forEach((d, i) => {
      const len = (c * d.value) / total;
      el('circle', { cx: 80, cy: 80, r, fill: 'none', stroke: colours[i % 4], 'stroke-width': 18, 'stroke-dasharray': `${Math.max(0, len - 2)} ${c}`, 'stroke-dashoffset': -at, transform: 'rotate(-90 80 80)' }, svg);
      at += len;
    });
    const t = el('text', { x: 80, y: 86, 'text-anchor': 'middle', 'font-size': 18, fill: 'var(--foreground)' }, svg);
    t.textContent = '$' + total;
  };
  draw();
}
function pie(host, data, o) {
  host.textContent = '';
  const svg = el('svg', { width: 160, height: 160, viewBox: '0 0 160 160', role: 'img', 'aria-label': o.title }, host);
  const total = data.reduce((s, d) => s + d, 0);
  let a0 = -Math.PI / 2;
  data.forEach((d, i) => {
    const a1 = a0 + (2 * Math.PI * d) / total, big = a1 - a0 > Math.PI ? 1 : 0;
    const p = (a) => `${80 + 70 * Math.cos(a)},${80 + 70 * Math.sin(a)}`;
    el('path', { d: `M80,80L${p(a0)}A70,70 0 ${big} 1 ${p(a1)}Z`, fill: o.colours[i % o.colours.length], stroke: 'var(--card)', 'stroke-width': 2 }, svg);
    a0 = a1;
  });
}
"""

BUDGET = "[{label:'Housing',value:1450},{label:'Groceries',value:520},{label:'Transport',value:260},{label:'Entertainment',value:180},{label:'Utilities',value:210},{label:'Healthcare',value:140},{label:'Savings',value:600}]"
MONTHS = "['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'].map((m,i)=>({label:m,value:[30,42,38,51,47,60,58,66,61,72,69,80][i]}))"


def _chart_page(calls: str, hosts: list[str]) -> str:
    body = "".join(f"<section class=card><h2>{h}</h2><div class=host id=h{i}></div></section>" for i, h in enumerate(hosts))
    return doc(body, script=LIB + calls)


GOOD = {
    "budget bars (7 categories, wrapped labels)": _chart_page(f"barChart(document.getElementById('h0'), {BUDGET}, {{title:'Monthly spending by category'}});", ["Spending"]),
    "many bars (24, thinned labels)": _chart_page("barChart(document.getElementById('h0'), Array.from({length:24},(_, i)=>({label:'Week '+(i+1),value:10+((i*37)%50)})), {title:'Weekly totals'});", ["Weekly"]),
    "bars in a side colour (destructive) and 11 px labels": _chart_page(f"barChart(document.getElementById('h0'), {BUDGET}, {{title:'Over budget', colour:'var(--destructive)', size:11}});", ["Over budget"]),
    "line chart, 12 months, dashed grid": _chart_page(f"lineChart(document.getElementById('h0'), {MONTHS}, {{title:'Balance by month'}});", ["Balance"]),
    "area chart with a gradient fill": _chart_page(f"lineChart(document.getElementById('h0'), {MONTHS}, {{title:'Savings', area:true}});", ["Savings"]),
    "horizontal bars with long labels": _chart_page(
        "hbarChart(document.getElementById('h0'), [{label:'Entertainment and streaming',value:180},{label:'Groceries',value:520},{label:'Public transport passes',value:90},{label:'Utilities',value:210}], {title:'Spending'});",
        ["Spending"],
    ),
    "donut on a muted track, legend row": doc(
        "<section class=card><h2>Split</h2><div id=h0></div><ul class=legend><li><i style='background:var(--primary)'></i>Housing</li><li><i style='background:var(--foreground)'></i>Food</li><li><i style='background:var(--destructive)'></i>Fun</li><li><i style='background:var(--muted-foreground)'></i>Other</li></ul></section>",
        style=".legend{display:flex;flex-wrap:wrap;gap:4px 12px;list-style:none;padding:0;margin:8px 0 0;font-size:12px;color:var(--muted-foreground)}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px}",
        script=LIB + "donut(document.getElementById('h0'), [{value:1450},{value:520},{value:180},{value:300}], {title:'Budget split'});",
    ),
    "pie in four theme colours": _chart_page("pie(document.getElementById('h0'), [45, 25, 20, 10], {title:'Budget split', colours:['var(--primary)','var(--foreground)','var(--destructive)','var(--muted-foreground)']});", ["Split"]),
    "viewBox chart, rotated labels": doc(
        "<section class=card><h2>Rotated</h2><svg viewBox='0 0 720 340' style='width:100%;height:auto' role=img aria-label='Spending chart'><title>Spending chart</title>"
        + "".join(
            f"<rect x='{100 + i * 84}' y='{200 - v}' width='56' height='{v}' fill='var(--primary)'/><text transform='translate({128 + i * 84} 222) rotate(-35)' text-anchor='end' font-size='20' fill='var(--muted-foreground)'>{name}</text>"
            for i, (name, v) in enumerate([("Housing", 180), ("Groceries", 90), ("Transport", 60), ("Entertainment", 40), ("Utilities", 50), ("Healthcare", 30), ("Savings", 120)])
        )
        + "<line x1='90' x2='710' y1='200' y2='200' stroke='var(--border)'/></svg></section>"
    ),
    "labels with a halo (stroke copy under each label), value labels on bars": doc(
        "<section class=card><h2>Halo</h2><svg viewBox='0 0 320 180' style='width:100%;height:auto' role=img aria-label='Chart'>"
        + "".join(
            f"<rect x='{20 + i * 74}' y='{150 - v}' width='50' height='{v}' fill='var(--primary)'/>"
            f"<text x='{45 + i * 74}' y='{144 - v}' text-anchor='middle' font-size='12' stroke='var(--card)' stroke-width='3' fill='none'>{v}</text>"
            f"<text x='{45 + i * 74}' y='{144 - v}' text-anchor='middle' font-size='12' fill='var(--foreground)'>{v}</text>"
            f"<text x='{45 + i * 74}' y='168' text-anchor='middle' font-size='12' fill='var(--muted-foreground)'>{name}</text>"
            for i, (name, v) in enumerate([("Mon", 80), ("Tue", 120), ("Wed", 60), ("Thu", 100)])
        )
        + "</svg></section>"
    ),
    "HTML bar chart with wrapping labels": doc(
        "<section class=card><h2>Spending</h2><div class=bars role=img aria-label='Spending by category'>"
        + "".join(
            f"<div class=col><div class=bar style='height:{v}px'></div><span class=lab>{name}</span></div>"
            for name, v in [("Housing", 140), ("Groceries", 60), ("Transport", 30), ("Entertainment", 20), ("Utilities", 25), ("Healthcare", 15), ("Savings", 70)]
        )
        + "</div></section>",
        style=".bars{display:flex;align-items:flex-end;gap:4px;height:200px}.col{flex:1;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:4px}"
        ".bar{width:70%;background:var(--primary);border-radius:3px 3px 0 0}.lab{font-size:11px;color:var(--muted-foreground);text-align:center;overflow-wrap:anywhere;hyphens:auto;line-height:1.2;max-width:100%}",
    ),
    "ellipsised legend labels (CSS truncation is allowed)": doc(
        "<section class=card><h2>Legend</h2><div class=leg>"
        + "".join(f"<span class=item><i></i><span class=t>{n}</span></span>" for n in ["Entertainment and streaming services", "Groceries and household", "Transport and fuel"])
        + "</div></section>",
        style=".leg{display:flex;gap:8px}.item{flex:1;min-width:0;display:flex;align-items:center;gap:4px;font-size:12px}.item i{flex:none;width:10px;height:10px;background:var(--primary)}"
        ".t{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    ),
}


def kit_page() -> str:
    """The Apps kit's own chart parts (omni-react.tsx Sparkline and Timeline,
    as they render), styled by the kit's real CSS."""
    css = (KIT / "graphite-tokens.css").read_text(encoding="utf-8") + (KIT / "primitives.css").read_text(encoding="utf-8")
    days = [("Mon", 3), ("Tue", 5), ("Wed", 2), ("Thu", 7), ("Fri", 4), ("Sat", 1), ("Sun", 6)]
    spark = (
        f"<svg class='omni-chart omni-sparkline' viewBox='0 0 {len(days) * 14} 28' role=img aria-label='Runs: "
        + ", ".join(f"{d} {v}" for d, v in days)
        + "'>"
        + "".join(f"<rect x='{i * 14 + 2}' y='{26 - round(v / 7 * 24)}' width='10' height='{max(1, round(v / 7 * 24))}' rx='2' class='omni-series'/>" for i, (d, v) in enumerate(days))
        + "</svg>"
    )
    W, top, bar = 720, 8, 30
    events = [(9 * 60, 9 * 60 + 30, "Standup"), (11 * 60, 12 * 60 + 30, "Design review with the team"), (14 * 60, 15 * 60, "1:1"), (16 * 60, 17 * 60 + 30, "Planning")]
    x = lambda m: max(0, min(W, (m - 8 * 60) / (11 * 60) * W))  # noqa: E731
    blocks = ""
    for a, b, title in events:
        xa, w = x(a), max(3, x(b) - x(a))
        label = f"<text x='{xa + 6}' y='{top + bar / 2 + 4}' class='omni-timeline-label'>{title}</text>" if len(title) * 7 + 12 <= w else ""
        blocks += f"<g><title>{title}</title><rect x='{xa}' y='{top}' width='{w}' height='{bar}' rx='4' class='omni-series'/>{label}</g>"
    hours = "".join(f"<text x='{min(max(x(h * 60), 10), W - 10)}' y='78' text-anchor='middle' class='omni-timeline-hour'>{h % 12 or 12}{'a' if h < 12 else 'p'}</text>" for h in range(8, 20))
    timeline = (
        f"<div class=omni-timeline role=img aria-label='Today'><svg class=omni-chart viewBox='0 0 {W} 84' preserveAspectRatio='xMinYMin meet'>"
        "<defs><pattern id=omni-free width=6 height=6 patternUnits=userSpaceOnUse patternTransform='rotate(45)'><line x1=0 y1=0 x2=0 y2=6 class=omni-free-line /></pattern></defs>"
        f"<rect x=0 y='{top}' width='{W}' height='{bar}' fill='url(#omni-free)' class=omni-free />{blocks}"
        f"<line x1='{x(13 * 60)}' x2='{x(13 * 60)}' y1='4' y2='42' class=omni-now />{hours}</svg></div>"
    )
    body = (
        "<main class=omni-grid style='padding:16px'>"
        f"<section class=omni-tile><div class=omni-tile-head><h3 class=omni-tile-title>Runs this week</h3><span class=omni-tile-meta>updated just now</span></div>{spark}</section>"
        f"<section class=omni-tile><div class=omni-tile-head><h3 class=omni-tile-title>Today</h3></div>{timeline}</section>"
        "</main>"
    )
    return doc(body, style=css)


#: Each must fail with the words in the second item.
BAD = {
    "budget tracker: dark bars on the dark card, fixed-position nowrap labels": (
        doc(
            "<section class=card><h2>Budget</h2><div class=host id=h0></div></section>",
            script=LIB
            + f"""const data = {BUDGET};
const draw = () => {{ const host = document.getElementById('h0'); host.textContent = ''; const W = host.clientWidth, H = 220;
  const svg = el('svg', {{ width: W, height: H }}, host);
  const step = (W - 20) / data.length, max = 1450;
  data.forEach((d, i) => {{ const h = 160 * d.value / max; el('rect', {{ x: 10 + i * step + 4, y: 180 - h, width: step - 8, height: h, fill: '#1f2937' }}, svg);
    const t = el('text', {{ x: 10 + i * step + step / 2, y: 200, 'text-anchor': 'middle', 'font-size': 13, fill: 'var(--muted-foreground)' }}, svg); t.textContent = d.label; }});
}}; draw(); addEventListener('resize', draw);""",
        ),
        ["chart labels overlap at 360 px", "chart bars have too little contrast with the background in dark"],
    ),
    "overlap only: labels too wide for their slots": (
        _chart_page(
            "const host=document.getElementById('h0');const draw=()=>{const {svg,W}=frame(host,'Spending',200);const d="
            + BUDGET
            + ";const s=(W-20)/d.length;d.forEach((x,i)=>{el('rect',{x:10+i*s+3,y:150-x.value/10,width:s-6,height:x.value/10,fill:'var(--primary)'},svg);label(svg,10+i*s+s/2,170,[x.label],13);});};draw();addEventListener('resize',draw);",
            ["Spending"],
        ),
        ["chart labels overlap at 360 px"],
    ),
    "cut off only: last label runs past the svg's right edge": (
        doc(
            "<section class=card><h2>Cut</h2><svg width=300 height=120 role=img aria-label='chart'>"
            + "".join(
                f"<rect x='{10 + i * 70}' y='{90 - v}' width='40' height='{v}' fill='var(--primary)'/><text x='{30 + i * 70}' y='110' font-size='12' text-anchor='{'start' if i == 3 else 'middle'}' fill='var(--muted-foreground)'>{n}</text>"
                for i, (n, v) in enumerate([("Mon", 40), ("Tue", 60), ("Wed", 30), ("Entertainment", 70)])
            )
            + "</svg></section>"
        ),
        ["chart text is cut off at 360 px"],
    ),
    "contrast only: bars in var(--accent), a surface colour": (
        _chart_page(f"barChart(document.getElementById('h0'), {BUDGET}, {{title:'Spending', colour:'var(--accent)'}});", ["Spending"]),
        ["chart bars have too little contrast with the background in light", "chart bars have too little contrast with the background in dark"],
    ),
    "contrast only: a line in a hard-coded light grey (light theme fails)": (
        _chart_page(
            f"lineChart(document.getElementById('h0'), {MONTHS}, {{title:'Balance'}}); document.querySelectorAll('path,circle').forEach(n=>{{ if(n.getAttribute('stroke')) n.setAttribute('stroke','#e5e7eb'); if(n.tagName==='circle') n.setAttribute('fill','#e5e7eb'); }});",
            ["Balance"],
        ),
        ["have too little contrast with the background in light"],
    ),
    "contrast only: one donut arc in var(--muted)": (
        _chart_page("donut(document.getElementById('h0'), [{value:1450},{value:520},{value:180}], {title:'Budget split', colours:['var(--primary)','var(--muted)','var(--destructive)']});", ["Split"]),
        ["chart slices or areas have too little contrast with the background in light", "chart slices or areas have too little contrast with the background in dark"],
    ),
    "contrast only: a pie with a slice in var(--border)": (
        _chart_page("pie(document.getElementById('h0'), [45, 25, 30], {title:'Budget split', colours:['var(--primary)','var(--border)','var(--destructive)']});", ["Split"]),
        ["chart slices or areas have too little contrast with the background in light", "chart slices or areas have too little contrast with the background in dark"],
    ),
    "HTML row: nowrap labels spill into each other": (
        doc(
            "<section class=card><h2>Spending</h2><div class=bars>"
            + "".join(
                f"<div class=col><div class=bar style='height:{v}px'></div><span class=lab>{n}</span></div>"
                for n, v in [("Housing", 140), ("Groceries", 60), ("Transport", 30), ("Entertainment", 20), ("Utilities", 25), ("Healthcare", 15), ("Savings", 70)]
            )
            + "</div></section>",
            style=".bars{display:flex;align-items:flex-end;gap:2px;height:200px}.col{flex:1;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:flex-end}"
            ".bar{width:70%;background:var(--primary)}.lab{font-size:13px;white-space:nowrap;color:var(--muted-foreground)}",
        ),
        ["labels in a row overlap at 360 px"],
    ),
    "HTML row: labels cut by a hidden-overflow cell (no ellipsis)": (
        doc(
            "<section class=card><h2>Spending</h2><div class=row>" + "".join(f"<div class=cell>{n}</div>" for n in ["Housing", "Groceries", "Transport", "Entertainment", "Utilities"]) + "</div></section>",
            style=".row{display:flex;gap:4px}.cell{flex:1;min-width:0;overflow:hidden;white-space:nowrap;font-size:13px}",
        ),
        ["chart text is cut off at 360 px"],
    ),
}


ICON = "<svg width=24 height=24 viewBox='0 0 24 24' fill=none stroke=currentColor stroke-width=2 stroke-linecap=round stroke-linejoin=round aria-hidden=true>{}</svg>"
ICONS = [
    "<path d='M3 12h18M12 3v18'/>",
    "<circle cx=12 cy=12 r=9 /><path d='M12 7v5l3 3'/>",
    "<rect x=3 y=4 width=18 height=16 rx=2 /><path d='M3 10h18M8 2v4M16 2v4'/>",
    "<path d='M20 6 9 17l-5-5'/>",
]

ORDINARY = {
    "icons-only buttons and a large icon": doc(
        "<section class=card><h2>Actions</h2><div class=bar>"
        + "".join(f"<button aria-label=a{i}>{ICON.format(p)}</button>" for i, p in enumerate(ICONS))
        + "</div><svg width=64 height=64 viewBox='0 0 24 24' fill=none stroke='var(--muted)' stroke-width=1.5 aria-hidden=true><circle cx=12 cy=12 r=10 /><path d='M8 12h8'/></svg></section>",
        style=".bar{display:flex;gap:8px}button{display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--foreground)}",
    ),
    "a logo in the header": doc(
        "<header style='display:flex;align-items:center;gap:12px;padding:12px 16px;background:var(--card);border-bottom:1px solid var(--border)'>"
        "<svg width=140 height=40 viewBox='0 0 140 40' role=img aria-label='Ledgerly'><circle cx=20 cy=20 r=16 fill='var(--primary)'/><rect x=12 y=14 width=16 height=3 fill='var(--primary-foreground)'/>"
        "<rect x=12 y=19 width=16 height=3 fill='var(--primary-foreground)'/><rect x=12 y=24 width=10 height=3 fill='var(--primary-foreground)'/>"
        "<text x=44 y=26 font-size=18 font-weight=700 fill='var(--foreground)'>Ledgerly</text></svg><nav class=nav><a href='#a'>Home</a><a href='#b'>Budgets</a><a href='#c'>Reports</a><a href='#d'>Settings</a></nav></header>"
        "<main class=card><p>Welcome back. Your <a href='#x'>budget</a> for <strong>November</strong> is on <em>track</em>.</p></main>",
        style=".nav{display:flex;gap:12px;font-size:14px}.nav a{color:var(--muted-foreground);text-decoration:none}a{color:var(--primary)}",
    ),
    "a one-colour petal mark in a fixed navy (a logo, dark on dark in the dark theme)": doc(
        "<header class=card style='display:flex;align-items:center;gap:8px'><svg width=48 height=48 viewBox='0 0 48 48' role=img aria-label='Petal'>"
        "<path d='M24 24C24 12 30 6 36 6C36 14 32 22 24 24Z' fill='#1e3a8a'/><path d='M24 24C36 24 42 30 42 36C34 36 26 32 24 24Z' fill='#1e3a8a'/>"
        "<path d='M24 24C24 36 18 42 12 42C12 34 16 26 24 24Z' fill='#1e3a8a'/><path d='M24 24C12 24 6 18 6 12C14 12 22 16 24 24Z' fill='#1e3a8a'/></svg><strong>Petal Finance</strong></header>"
    ),
    "KPI cards with a sparkline (no labels)": doc(
        "<section class=kpis>"
        + "".join(
            f"<div class=card><div class=v>{v}</div><div class=l>{lbl}</div><svg width=120 height=32 viewBox='0 0 120 32' aria-hidden=true><polyline points='0,24 20,18 40,22 60,10 80,14 100,6 120,9' fill=none stroke='var(--primary)' stroke-width=2 /></svg></div>"
            for v, lbl in [("$3,360", "Spent"), ("$640", "Left"), ("18%", "Saved")]
        )
        + "</section>",
        style=".kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}.v{font-size:24px;font-weight:700}.l{font-size:12px;color:var(--muted-foreground)}",
    ),
    "a table of transactions": doc(
        "<section class=card><h2>Transactions</h2><div style='overflow-x:auto'><table><thead><tr><th>Date</th><th>Payee</th><th>Category</th><th>Amount</th></tr></thead><tbody>"
        + "".join(
            f"<tr><td>Nov {d}</td><td>{p}</td><td>{c}</td><td>{a}</td></tr>"
            for d, p, c, a in [(1, "Rent", "Housing", "$1,450"), (3, "Fresh Market", "Groceries", "$86.20"), (5, "City Transit", "Transport", "$45.00"), (9, "Cinema", "Entertainment", "$24.00")]
        )
        + "</tbody></table></div></section>",
        style="table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--border)}",
    ),
    "a form with labels, inputs and a button row": doc(
        "<form class=card><h2>Add expense</h2><label>Amount <input type=number value=12></label><label>Category <select><option>Groceries</option><option>Entertainment</option></select></label>"
        "<label>Note <textarea rows=2>Lunch</textarea></label><div class=row><button type=button>Cancel</button><button type=button>Save draft</button><button type=submit>Add</button></div><p class=sr>Form for adding an expense</p></form>",
        style="label{display:block;margin:8px 0;font-size:13px}input,select,textarea{display:block;width:100%;margin-top:4px;padding:6px;border:1px solid var(--border);border-radius:6px;background:var(--background);color:var(--foreground)}"
        ".row{display:flex;gap:8px;justify-content:flex-end}button{padding:8px 12px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--foreground)}"
        ".sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}",
    ),
    "decorative blobs, a loading skeleton and a collapsed panel": doc(
        "<section class=card style='position:relative;overflow:hidden'><svg width=300 height=160 viewBox='0 0 300 160' aria-hidden=true style='position:absolute;right:-40px;top:-40px'><circle cx=150 cy=80 r=70 fill='var(--muted)'/><circle cx=60 cy=40 r=30 fill='var(--muted)'/><circle cx=240 cy=130 r=24 fill='var(--muted)'/></svg>"
        "<h2>Insights</h2><svg width=240 height=60 viewBox='0 0 240 60' aria-hidden=true><rect x=0 y=0 width=240 height=12 rx=4 fill='var(--muted)'/><rect x=0 y=20 width=200 height=12 rx=4 fill='var(--muted)'/><rect x=0 y=40 width=160 height=12 rx=4 fill='var(--muted)'/></svg>"
        "<div style='max-height:0;overflow:hidden'><svg width=300 height=100><text x=10 y=20>Hidden label one</text><text x=10 y=22>Hidden label two</text></svg></div>"
        "<div class=tabs><button>Week</button><button>Month</button><button>Year</button><button>All time</button></div></section>",
        style=".tabs{display:flex;gap:4px;margin-top:8px}.tabs button{padding:6px 10px;border-radius:999px;border:1px solid var(--border);background:var(--card);color:var(--foreground);font-size:13px}",
    ),
}
