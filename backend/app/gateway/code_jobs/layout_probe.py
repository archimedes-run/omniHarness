"""The layout check for a coding job's web app (spec 009): the script itself.

NOT imported by the gateway. The gateway writes this file into the sandbox,
runs it only if its checksum matches, with the image's own root-owned Python
(`python3.10 -I -S`: the standard library only, no site packages, no
environment) and the browser already in the image. Usage:

    python3.10 -I -S layout_probe.py <site root> <result file> [app]

With `app` (Spec 011 FR-026) the site is an app's MOCK build: its index.html
reads `?state=` and `?theme=` and answers every source in that state. It is
loaded once per theme and state and measured at each width, served with the
app CSP the gateway wrote to check.json beside the result file; the check
also measures contrast, text sizes and touch targets, reads the tile words
and the page's blocked requests (Content-Security-Policy violations, watched
from an isolated world), and saves a PNG screenshot per theme and width of
the fresh state beside the result file.

It serves <site root> on 127.0.0.1 (a port the system picks, closed when it
ends), drives the browser headless over a private pipe (no debugging port),
loads the page at each width and measures it from an isolated world (the
page's own scripts cannot replace the functions the measurement uses). Every
request to anything but that local server is refused. The result is one
small JSON file, every string in it clipped; the gateway parses it again,
strictly. It must run on Python 3.10.
"""

import base64
import fcntl
import http.server
import json
import os
import signal
import sys
import tempfile
import threading
import time
import urllib.parse

WIDTHS = (360, 560, 1280)
HEIGHT = 800
BROWSER = "/usr/local/bin/browser"
LOAD_S = 10.0
SETTLE_S = 0.8
CALL_S = 8.0
OVERALL_S = 38.0
MAX_MESSAGE = 4 << 20
MAX_RESULT = 16384
APP_THEMES = ("light", "dark")
APP_STATES = ("fresh", "empty", "not_connected", "failed")
APP_OVERALL_S = 100.0
APP_MAX_RESULT = 98304
RESIZE_S = 0.35
SHOT_MAX_BYTES = 1_500_000
SHOT_MAX_HEIGHT = 2400
PNG = b"\x89PNG\r\n\x1a\n"
WORLD = "omni-app-check"
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".wasm": "application/wasm",
    ".txt": "text/plain",
}
FLAGS = [
    "--headless",
    # The image strips every setuid bit and the gateway starts sandboxes with
    # no-new-privileges, so the browser's own sandbox cannot start. The page
    # then runs as the sandbox user, with the rights the worker's code had.
    "--no-sandbox",
    "--remote-debugging-pipe",
    "--no-proxy-server",
    "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
    "--block-new-web-contents",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-sync",
    "--disable-crash-reporter",
    "--no-first-run",
    "--no-default-browser-check",
    "--mute-audio",
    "--hide-scrollbars",
    "--noerrdialogs",
]

#: Runs in the page, in an isolated world. Returns numbers and short,
#: filtered strings only.
MEASURE = r"""
(function () {
  const de = document.documentElement;
  const body = document.body;
  const cw = de.clientWidth;
  const safe = (s) => String(s).replace(/[^A-Za-z0-9_-]/g, '').slice(0, 40);
  const name = (el) => {
    let s = el.tagName.toLowerCase().replace(/[^a-z0-9-]/g, '').slice(0, 20);
    if (el.id) s += '#' + safe(el.id);
    const cls = el.classList ? Array.from(el.classList).slice(0, 2).map(safe).filter(Boolean) : [];
    if (cls.length) s += '.' + cls.join('.');
    return s;
  };
  const where = (el) => {
    let p = el.parentElement;
    for (let i = 0; p && i < 6; i++, p = p.parentElement) {
      if (p.id || (p.classList && p.classList.length)) return name(el) + ' in ' + name(p);
    }
    return name(el);
  };
  const overflow = Math.max(0, de.scrollWidth - cw);
  const offenders = [];
  if (overflow > 1 && body) {
    const all = body.getElementsByTagName('*');
    for (let i = 0; i < all.length && i < 5000 && offenders.length < 3; i++) {
      const el = all[i];
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.right <= cw + 1) continue;
      const parent = el.parentElement;
      if (parent && parent !== body && parent.getBoundingClientRect().right > cw + 1) continue;
      const text = where(el);
      if (!offenders.includes(text)) offenders.push(text);
    }
  }
  let visuals = 0;
  if (body) {
    const items = body.querySelectorAll('img,svg,canvas,video,input,button,select,textarea');
    for (let i = 0; i < items.length && i < 300; i++) {
      const r = items[i].getBoundingClientRect();
      if (r.width > 0 && r.height > 0) visuals++;
    }
  }
  const text = body ? (body.innerText || '').trim().length : 0;

  // Charts: drawn content (each shape's geometry plus half its stroke, in
  // screen pixels) against the outer <svg>'s own box, which clips it.
  const svgs = [];
  const SHAPES = 'path,circle,ellipse,rect,line,polyline,polygon,text,image,use';
  const list = document.querySelectorAll('svg');
  for (let i = 0; i < list.length && i < 100 && svgs.length < 5; i++) {
    const svg = list[i];
    if (svg.ownerSVGElement) continue;
    const r = svg.getBoundingClientRect();
    if (r.width < 24 || r.height < 24) continue; // icons
    const cs = getComputedStyle(svg);
    if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue; // nothing is cut by the svg itself
    const px = (v) => parseFloat(v) || 0;
    const box = {
      left: r.left + px(cs.borderLeftWidth) + px(cs.paddingLeft),
      right: r.right - px(cs.borderRightWidth) - px(cs.paddingRight),
      top: r.top + px(cs.borderTopWidth) + px(cs.paddingTop),
      bottom: r.bottom - px(cs.borderBottomWidth) - px(cs.paddingBottom),
    };
    const tolX = Math.max(6, 0.04 * (box.right - box.left));
    const tolY = Math.max(6, 0.04 * (box.bottom - box.top));
    const worst = { shape: null, text: null };
    const shapes = svg.querySelectorAll(SHAPES);
    for (let j = 0; j < shapes.length && j < 3000; j++) {
      const el = shapes[j];
      if (el.closest('defs,clipPath,mask,pattern,marker,symbol,[clip-path],[mask]')) continue;
      if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) continue;
      let bb;
      try { bb = el.getBBox(); } catch (e) { continue; }
      if (!bb || (bb.width === 0 && bb.height === 0)) continue;
      const m = el.getScreenCTM();
      if (!m) continue;
      const es = getComputedStyle(el);
      const half = es.stroke && es.stroke !== 'none' ? px(es.strokeWidth) / 2 : 0;
      const x0 = bb.x - half, y0 = bb.y - half, x1 = bb.x + bb.width + half, y1 = bb.y + bb.height + half;
      const xs = [], ys = [];
      for (const [x, y] of [[x0, y0], [x1, y0], [x0, y1], [x1, y1]]) {
        xs.push(m.a * x + m.c * y + m.e);
        ys.push(m.b * x + m.d * y + m.f);
      }
      const kind = el.tagName.toLowerCase() === 'text' ? 'text' : 'shape';
      for (const [side, amount, tol] of [
        ['left', box.left - Math.min(...xs), tolX],
        ['right', Math.max(...xs) - box.right, tolX],
        ['top', box.top - Math.min(...ys), tolY],
        ['bottom', Math.max(...ys) - box.bottom, tolY],
      ]) {
        if (amount > tol && (!worst[kind] || amount > worst[kind].px)) worst[kind] = { where: where(svg), side, px: Math.round(amount), kind };
      }
    }
    const found = worst.shape || worst.text;
    if (found) svgs.push(found);
  }
  return { overflow_px: Math.round(overflow), client_width: cw, offenders, rendered: !!body && (text > 0 || visuals > 0), svgs };
})()
"""


#: Added to every new document of an app run, in the check's isolated world:
#: records the page's blocked requests and Trusted Types refusals. The page's
#: own scripts cannot see or remove this listener.
APP_WATCH = r"""
(function () {
  const seen = [];
  window.__omniViolations = seen;
  document.addEventListener('securitypolicyviolation', function (e) {
    if (seen.length < 20) seen.push(String(e.effectiveDirective || e.violatedDirective || '').replace(/[^a-z-]/g, '').slice(0, 40));
  }, true);
})()
"""

#: Runs in the page, in the isolated world, after MEASURE: contrast, small
#: text, small touch targets, nested frames, and the tile words. Returns
#: numbers, booleans and short filtered strings only.
APP_MEASURE = r"""
(function (cfg) {
  const de = document.documentElement;
  const body = document.body;
  const safe = (s) => String(s).replace(/[^A-Za-z0-9_-]/g, '').slice(0, 40);
  const name = (el) => {
    let s = el.tagName.toLowerCase().replace(/[^a-z0-9-]/g, '').slice(0, 20);
    if (el.id) s += '#' + safe(el.id);
    const cls = el.classList ? Array.from(el.classList).slice(0, 2).map(safe).filter(Boolean) : [];
    if (cls.length) s += '.' + cls.join('.');
    return s;
  };
  const where = (el) => {
    let p = el.parentElement;
    for (let i = 0; p && i < 6; i++, p = p.parentElement) {
      if (p.id || (p.classList && p.classList.length)) return name(el) + ' in ' + name(p);
    }
    return name(el);
  };
  const canvas = document.createElement('canvas');
  canvas.width = 1; canvas.height = 1;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const memo = new Map();
  // Any CSS colour (oklch, color-mix, named) to sRGB through a canvas pixel.
  const rgba = (c) => {
    if (memo.has(c)) return memo.get(c);
    let v = [0, 0, 0, 0];
    if (c && c !== 'transparent') {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = '#000';
      ctx.fillStyle = c;
      ctx.fillRect(0, 0, 1, 1);
      const d = ctx.getImageData(0, 0, 1, 1).data;
      v = [d[0], d[1], d[2], d[3] / 255];
    }
    memo.set(c, v);
    return v;
  };
  const over = (top, under) => {
    const a = top[3];
    return [top[0] * a + under[0] * (1 - a), top[1] * a + under[1] * (1 - a), top[2] * a + under[2] * (1 - a), 1];
  };
  const lum = (c) => {
    const f = (x) => { x /= 255; return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const canvasColour = cfg.theme === 'dark' ? [18, 18, 18, 1] : [255, 255, 255, 1];
  // The background under an element: its own and its ancestors' colours,
  // composited; null when an image or gradient is under it (not measured).
  const backdrop = (el) => {
    const layers = [];
    let opacity = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return null;
      const op = parseFloat(cs.opacity);
      if (!isNaN(op)) opacity *= op;
      const c = rgba(cs.backgroundColor);
      if (c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
    }
    let bg = canvasColour;
    for (let i = layers.length - 1; i >= 0; i--) bg = over(layers[i], bg);
    return { bg, opacity };
  };
  const visible = (el) => {
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const low = new Map();
  const small = new Map();
  let measured = 0;
  let lowCount = 0;
  let smallCount = 0;
  if (body) {
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    const done = new Set();
    for (let node = walker.nextNode(), i = 0; node && i < 4000; node = walker.nextNode(), i++) {
      if (!node.nodeValue || !node.nodeValue.trim()) continue;
      const el = node.parentElement;
      if (!el || done.has(el)) continue;
      done.add(el);
      const tag = el.tagName.toLowerCase();
      if (tag === 'script' || tag === 'style' || tag === 'noscript' || tag === 'title') continue;
      if (!visible(el)) continue;
      const cs = getComputedStyle(el);
      const isSvg = el instanceof SVGElement;
      let size = parseFloat(cs.fontSize) || 0;
      if (isSvg && el.getScreenCTM) {
        const m = el.getScreenCTM();
        if (m) size *= Math.sqrt(Math.abs(m.a * m.d - m.b * m.c));
      }
      const label = where(el);
      if (size > 0 && size < 11.5) {
        smallCount++;
        if (!small.has(label)) small.set(label, Math.round(size * 10) / 10);
      }
      const back = backdrop(el);
      if (!back) continue;
      let fg = rgba(isSvg ? cs.fill : cs.color);
      if (fg[3] === 0) continue;
      fg = [fg[0], fg[1], fg[2], fg[3] * back.opacity];
      const shown = over(fg, back.bg);
      const r = ratio(shown, back.bg);
      const bold = parseInt(cs.fontWeight, 10) >= 700;
      const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
      measured++;
      if (r + 0.005 < need) {
        lowCount++;
        const prev = low.get(label);
        if (!prev || r < prev.ratio) low.set(label, { where: label, ratio: Math.round(r * 100) / 100, need });
      }
    }
  }
  const targets = new Map();
  let targetCount = 0;
  const controls = document.querySelectorAll('button,[role=button],input:not([type=hidden]),select,a[href]');
  for (let i = 0; i < controls.length && i < 1000; i++) {
    const el = controls[i];
    if (!visible(el)) continue;
    if (el.tagName === 'A' && getComputedStyle(el).display === 'inline') continue; // a link in running text
    const r = el.getBoundingClientRect();
    if (r.width < 23.5 || r.height < 23.5) {
      targetCount++;
      const label = where(el);
      if (!targets.has(label)) targets.set(label, [Math.round(r.width), Math.round(r.height)]);
    }
  }
  const text = body ? (body.innerText || '') : '';
  const count = (re) => (text.match(re) || []).length;
  let connect = 0;
  const buttons = document.querySelectorAll('button,[role=button],a');
  for (let i = 0; i < buttons.length && i < 1000; i++) {
    if (visible(buttons[i]) && /^\s*connect\b/i.test(buttons[i].innerText || buttons[i].getAttribute('aria-label') || '')) connect++;
  }
  const found = {};
  for (const [source, needles] of Object.entries(cfg.sentinels || {})) {
    found[source] = needles.some((n) => n && text.indexOf(n) !== -1);
  }
  return {
    contrast_measured: measured,
    contrast_low: lowCount,
    contrast: Array.from(low.values()).sort((a, b) => a.ratio - b.ratio).slice(0, 6),
    small_text: smallCount,
    small_text_where: Array.from(small.entries()).slice(0, 4).map(([w, px]) => ({ where: w, px })),
    small_targets: targetCount,
    small_targets_where: Array.from(targets.entries()).slice(0, 4).map(([w, s]) => ({ where: w, w: s[0], h: s[1] })),
    frames: document.querySelectorAll('iframe,frame,object,embed').length,
    doc_height: Math.max(de.scrollHeight, body ? body.scrollHeight : 0),
    words: {
      updated: count(/\bupdated\b/gi),
      ago: count(/\b(just now|\d+ min ago|\d+ h ago|\d+ days? ago)\b/gi),
      nothing: count(/nothing today/gi),
      not_connected: count(/not connected/gi),
      cant_tell: count(/can['\u2019]t tell/gi),
      connect,
      junk: count(/\bundefined\b|\bNaN\b|\[object Object\]|Invalid Date/g),
      reason: !!cfg.reason && text.indexOf(cfg.reason) !== -1,
    },
    sentinels: found,
  };
})
"""


def clip(value, n):
    text = "" if value is None else str(value)
    return "".join(c if c.isprintable() else " " for c in text)[:n]


class CdpError(Exception):
    pass


class Cdp:
    """The DevTools protocol over the browser's pipe: NUL-terminated JSON."""

    def __init__(self, write_fd, read_fd, on_event):
        self._w = write_fd
        self._r = read_fd
        self._on_event = on_event
        self._lock = threading.Lock()
        self._next = 0
        self._waiting = {}
        self.dead = ""
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        buf = bytearray()
        while True:
            try:
                chunk = os.read(self._r, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                return self._die("the browser closed its pipe")
            buf += chunk
            while True:
                end = buf.find(b"\x00")
                if end < 0:
                    break
                raw = bytes(buf[:end])
                del buf[: end + 1]
                self._handle(raw)
            if len(buf) > MAX_MESSAGE:
                return self._die("the page produced too much output")

    def _die(self, why):
        self.dead = why
        with self._lock:
            slots = list(self._waiting.values())
        for slot in slots:
            slot[0].set()

    def _handle(self, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        slot = None
        if "id" in msg:
            with self._lock:
                slot = self._waiting.pop(msg["id"], None)
        if slot is not None:
            slot[1] = msg
            slot[0].set()
        elif "method" in msg:
            try:
                self._on_event(msg)
            except Exception:  # noqa: BLE001 - one odd event never ends the check
                pass

    def _write(self, method, params, session):
        with self._lock:
            self._next += 1
            ident = self._next
            msg = {"id": ident, "method": method, "params": params or {}}
            if session:
                msg["sessionId"] = session
            data = json.dumps(msg).encode() + b"\x00"
            return ident, data

    def send(self, method, params=None, session=None):
        """Without waiting for the answer (from the reader thread)."""
        _, data = self._write(method, params, session)
        try:
            os.write(self._w, data)
        except OSError:
            pass

    def call(self, method, params=None, session=None, timeout=CALL_S):
        ident, data = self._write(method, params, session)
        slot = [threading.Event(), None]
        with self._lock:
            self._waiting[ident] = slot
        try:
            os.write(self._w, data)
        except OSError:
            raise CdpError("the browser closed its pipe") from None
        if not slot[0].wait(timeout):
            with self._lock:
                self._waiting.pop(ident, None)
            raise CdpError(method + " did not answer")
        if slot[1] is None:
            raise CdpError(self.dead or "the browser closed its pipe")
        if "error" in slot[1]:
            raise CdpError(clip((slot[1]["error"] or {}).get("message"), 120))
        return slot[1].get("result") or {}


def make_handler(root, csp=None):
    class SiteHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self._serve(True)

        def do_HEAD(self):
            self._serve(False)

        def _serve(self, body):
            try:
                rel = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip("/")
                real = os.path.realpath(os.path.join(root, rel))
                if os.path.isdir(real):
                    real = os.path.realpath(os.path.join(real, "index.html"))
                if not (real == root or real.startswith(root + os.sep)) or not os.path.isfile(real):
                    raise OSError("not served")
                size = os.path.getsize(real)
            except (OSError, ValueError):
                self.send_response(404)
                self.send_header("content-length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("content-type", TYPES.get(os.path.splitext(real)[1].lower(), "application/octet-stream"))
            self.send_header("content-length", str(size))
            self.send_header("cache-control", "no-store")
            # WebSockets are not paused by Fetch (below): this keeps them, and
            # every other connection the page makes, on this server.
            self.send_header("content-security-policy", csp or "connect-src 'self'")
            self.end_headers()
            if body:
                try:
                    with open(real, "rb") as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except OSError:
                    pass

    return SiteHandler


class Check:
    def __init__(self, root, out, app=False):
        self.root = root
        self.out = out
        self.app = app
        self.config = {}
        if app:
            self.result = {"v": 1, "mode": "app", "widths": list(WIDTHS), "themes": list(APP_THEMES), "states": list(APP_STATES), "runs": [], "shots": []}
        else:
            self.result = {"v": 1, "widths": list(WIDTHS), "pages": []}
        self.pages = {}
        self.origin = ""
        self.cdp = None
        self.pid = None
        self.server = None
        self.profile = None
        self._done = threading.Lock()

    def finish(self, **extra):
        if not self._done.acquire(blocking=False):
            return
        self.result.update(extra)
        text = json.dumps(self.result)
        if len(text) > (APP_MAX_RESULT if self.app else MAX_RESULT):
            text = json.dumps({"v": 1, "setup_error": "too_large"})
        try:
            fd = os.open(self.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(text)
        except OSError:
            pass  # the gateway reads "no result"
        if self.pid:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except OSError:
                pass
        if self.profile:
            # Only after the browser is gone.
            time.sleep(0.2)
            for base, dirs, files in os.walk(self.profile, topdown=False):
                for name in files:
                    try:
                        os.unlink(os.path.join(base, name))
                    except OSError:
                        pass
                for name in dirs:
                    try:
                        os.rmdir(os.path.join(base, name))
                    except OSError:
                        pass
            try:
                os.rmdir(self.profile)
            except OSError:
                pass
        os._exit(0)

    def why_not_started(self, exc):
        """Its exit status and the last line it logged (it has loaded no page yet)."""
        status = ""
        try:
            pid, code = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                status = f"signal {os.WTERMSIG(code)}" if os.WIFSIGNALED(code) else f"exit {os.WEXITSTATUS(code)}"
        except OSError:
            pass
        last = ""
        try:
            with open(os.path.join(self.profile, "browser.log"), "rb") as f:
                f.seek(max(0, os.path.getsize(f.name) - 4096))
                lines = [ln for ln in f.read().decode("utf-8", "replace").splitlines() if ln.strip() and "dbus" not in ln]
                last = lines[-1] if lines else ""
        except OSError:
            pass
        return clip("; ".join(x for x in (status or clip(exc, 40), last) if x), 160)

    def on_event(self, msg):
        page = self.pages.get(msg.get("sessionId"))
        if page is None:
            return
        method, p = msg.get("method"), msg.get("params") or {}
        session = msg.get("sessionId")
        if method == "Fetch.requestPaused":
            url = (p.get("request") or {}).get("url")
            ok = isinstance(url, str) and (url == self.origin or url.startswith(self.origin + "/"))
            if ok:
                self.cdp.send("Fetch.continueRequest", {"requestId": p.get("requestId")}, session)
            else:
                self.cdp.send("Fetch.failRequest", {"requestId": p.get("requestId"), "errorReason": "BlockedByClient"}, session)
        elif method == "Page.loadEventFired":
            page["_loaded"].set()
        elif method == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails") or {}
            text = clip(((d.get("exception") or {}).get("description")) or d.get("text") or "error", 120).split("  ")[0].strip()
            if text.startswith("ResizeObserver loop"):
                return  # reported by browsers for a harmless resize loop
            page["errors"] += 1
            if not page["first_error"]:
                page["first_error"] = text
        elif method == "Page.javascriptDialogOpening":
            self.cdp.send("Page.handleJavaScriptDialog", {"accept": False}, session)
        elif method == "Runtime.executionContextCreated":
            ctx = p.get("context") or {}
            aux = ctx.get("auxData") or {}
            if ctx.get("name") == WORLD and aux.get("isDefault") is False:
                # One per frame (a nested frame gets its own); the newest wins.
                page.setdefault("_worlds", {})[aux.get("frameId")] = ctx.get("id")
        elif method == "Inspector.targetCrashed":
            page["crashed"] = True
            page["_loaded"].set()

    def check_width(self, width):
        page = {"width": width, "loaded": False, "crashed": False, "errors": 0, "first_error": ""}
        cdp = self.cdp
        target = cdp.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = cdp.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        page["_loaded"] = threading.Event()
        self.pages[session] = page
        try:
            cdp.call("Fetch.enable", {"patterns": [{"urlPattern": "*"}]}, session)
            cdp.call("Page.enable", None, session)
            cdp.call("Runtime.enable", None, session)
            cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False}, session)
            nav = cdp.call("Page.navigate", {"url": self.origin + "/"}, session)
            if nav.get("errorText"):
                page["load_error"] = "nav"
                return page
            arrived = page["_loaded"].wait(LOAD_S)
            if page["crashed"]:
                page["load_error"] = "crashed"
                return page
            if not arrived:
                page["load_error"] = "slow"
                return page
            time.sleep(SETTLE_S)
            frame = cdp.call("Page.getFrameTree", None, session)["frameTree"]["frame"]["id"]
            world = cdp.call("Page.createIsolatedWorld", {"frameId": frame, "worldName": "omni-layout-check"}, session)
            res = cdp.call("Runtime.evaluate", {"expression": MEASURE, "contextId": world["executionContextId"], "returnByValue": True}, session)
            value = (res.get("result") or {}).get("value")
            if res.get("exceptionDetails") or not isinstance(value, dict):
                page["load_error"] = "unmeasurable"
                return page
            page.update(value)
            page["loaded"] = True
            return page
        except (CdpError, KeyError, TypeError):
            page["load_error"] = "crashed" if page["crashed"] else "no_response"
            return page
        finally:
            self.pages.pop(session, None)
            page.pop("_loaded", None)
            try:
                cdp.call("Target.closeTarget", {"targetId": target}, timeout=3)
            except CdpError:
                pass

    def _evaluate(self, expression, world, session):
        res = self.cdp.call("Runtime.evaluate", {"expression": expression, "contextId": world, "returnByValue": True}, session)
        if res.get("exceptionDetails"):
            return None
        return (res.get("result") or {}).get("value")

    def _shot(self, session, theme, width, height):
        """A PNG of the page at this width (its top SHOT_MAX_HEIGHT px),
        saved beside the result file."""
        height = max(1, min(int(height or HEIGHT), SHOT_MAX_HEIGHT))
        entry = {"theme": theme, "width": width}
        try:
            res = self.cdp.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True, "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1}}, session, timeout=15)
            data = base64.b64decode(res.get("data") or "", validate=True)
        except (CdpError, ValueError, TypeError):
            return {**entry, "skipped": "failed"}
        if not data.startswith(PNG):
            return {**entry, "skipped": "failed"}
        if len(data) > SHOT_MAX_BYTES:
            return {**entry, "skipped": "too_large"}
        name = f"shot-{theme}-{width}.png"
        try:
            fd = os.open(os.path.join(os.path.dirname(os.path.abspath(self.out)), name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except OSError:
            return {**entry, "skipped": "failed"}
        return {**entry, "file": name, "bytes": len(data), "height": height}

    def check_app_run(self, theme, state):
        """One theme and state of the mock build, measured at every width."""
        run = {"theme": theme, "state": state, "loaded": False, "crashed": False, "errors": 0, "first_error": "", "pages": [], "violations": [], "watched": False}
        cdp = self.cdp
        target = cdp.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = cdp.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        run["_loaded"] = threading.Event()
        self.pages[session] = run
        cfg = json.dumps({"theme": theme, "sentinels": self.config.get("sentinels") or {}, "reason": self.config.get("reason") or ""})
        expression = "(function () { const base = " + MEASURE.strip() + "; base.app = " + APP_MEASURE.strip() + "(" + cfg + "); return base; })()"
        try:
            cdp.call("Fetch.enable", {"patterns": [{"urlPattern": "*"}]}, session)
            cdp.call("Page.enable", None, session)
            cdp.call("Runtime.enable", None, session)
            cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": APP_WATCH, "worldName": WORLD}, session)
            cdp.call("Emulation.setDeviceMetricsOverride", {"width": WIDTHS[0], "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False}, session)
            nav = cdp.call("Page.navigate", {"url": f"{self.origin}/?state={state}&theme={theme}"}, session)
            if nav.get("errorText"):
                run["load_error"] = "nav"
                return run
            arrived = run["_loaded"].wait(LOAD_S)
            if run["crashed"]:
                run["load_error"] = "crashed"
                return run
            if not arrived:
                run["load_error"] = "slow"
                return run
            time.sleep(SETTLE_S)
            frame = cdp.call("Page.getFrameTree", None, session)["frameTree"]["frame"]["id"]
            world = (run.get("_worlds") or {}).get(frame)
            if world is not None:
                run["watched"] = True
            else:
                world = cdp.call("Page.createIsolatedWorld", {"frameId": frame, "worldName": WORLD + "-late"}, session)["executionContextId"]
            for i, width in enumerate(WIDTHS):
                if i:
                    cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False}, session)
                    time.sleep(RESIZE_S)
                value = self._evaluate(expression, world, session)
                if not isinstance(value, dict) or not isinstance(value.get("app"), dict):
                    run["load_error"] = "unmeasurable"
                    return run
                value["width"] = width
                run["pages"].append(value)
                if state == "fresh":
                    self.result["shots"].append(self._shot(session, theme, width, value["app"].get("doc_height")))
            if run["watched"]:
                found = self._evaluate("(window.__omniViolations || []).slice(0, 20)", world, session)
                run["violations"] = [clip(v, 40) for v in found] if isinstance(found, list) else []
            run["loaded"] = True
            return run
        except (CdpError, KeyError, TypeError):
            run["load_error"] = "crashed" if run["crashed"] else "no_response"
            return run
        finally:
            self.pages.pop(session, None)
            run.pop("_loaded", None)
            run.pop("_worlds", None)
            try:
                cdp.call("Target.closeTarget", {"targetId": target}, timeout=3)
            except CdpError:
                pass

    def run(self):
        if self.app:
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(self.out)), "check.json"), encoding="utf-8") as f:
                    raw = json.load(f)
                self.config = raw if isinstance(raw, dict) else {}
            except (OSError, ValueError):
                self.config = {}
        threading.Timer(APP_OVERALL_S if self.app else OVERALL_S, lambda: self.finish(timed_out=True)).start()
        try:
            root = os.path.realpath(self.root)
            if not os.path.isdir(root):
                raise OSError
        except OSError:
            return self.finish(setup_error="site_missing")
        try:
            http.server.ThreadingHTTPServer.daemon_threads = True
            csp = self.config.get("csp") if self.app and isinstance(self.config.get("csp"), str) else None
            self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(root, csp))
        except OSError:
            return self.finish(setup_error="server")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"
        # Short paths: the browser puts a Unix socket under its temp folder,
        # and a socket path longer than 107 bytes stops it from starting.
        work = os.path.dirname(os.path.abspath(self.out))
        self.profile = tempfile.mkdtemp(prefix="p-", dir=work)
        to_browser_r, to_browser_w = os.pipe()
        from_browser_r, from_browser_w = os.pipe()
        # Out of the way of fds 3 and 4, which the browser reads and writes.
        child_in = fcntl.fcntl(to_browser_r, fcntl.F_DUPFD_CLOEXEC, 10)
        child_out = fcntl.fcntl(from_browser_w, fcntl.F_DUPFD_CLOEXEC, 10)
        os.close(to_browser_r)
        os.close(from_browser_w)
        env = {"PATH": "/usr/bin:/bin", "HOME": self.profile, "TMPDIR": work, "LANG": "C.UTF-8"}
        marker = os.environ.get("OMNI_JOB_ID")
        if marker:
            env["OMNI_JOB_ID"] = marker  # the job's cleanup finds the browser by it
        try:
            self.pid = os.posix_spawn(
                BROWSER,
                [BROWSER, *FLAGS, "--user-data-dir=" + self.profile, "about:blank"],
                env,
                file_actions=[
                    (os.POSIX_SPAWN_OPEN, 0, "/dev/null", os.O_RDONLY, 0),
                    (os.POSIX_SPAWN_OPEN, 1, "/dev/null", os.O_WRONLY, 0),
                    # Its own log, read only when it fails to start (before any page loads).
                    (os.POSIX_SPAWN_OPEN, 2, os.path.join(self.profile, "browser.log"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600),
                    (os.POSIX_SPAWN_DUP2, child_in, 3),
                    (os.POSIX_SPAWN_DUP2, child_out, 4),
                ],
                setsid=True,
            )
        except OSError as exc:
            return self.finish(setup_error="browser", detail=clip(exc, 80))
        finally:
            os.close(child_in)
            os.close(child_out)
        self.cdp = Cdp(to_browser_w, from_browser_r, self.on_event)
        try:
            self.cdp.call("Browser.getVersion", timeout=15)
        except CdpError as exc:
            return self.finish(setup_error="browser", detail=self.why_not_started(exc))
        if self.app:
            for theme in APP_THEMES:
                for state in APP_STATES:
                    if self.cdp.dead:
                        return self.finish(browser_exit=True)
                    try:
                        self.result["runs"].append(self.check_app_run(theme, state))
                    except CdpError:
                        return self.finish(browser_exit=True)
            return self.finish()
        for width in WIDTHS:
            if self.cdp.dead:
                return self.finish(browser_exit=True)
            try:
                self.result["pages"].append(self.check_width(width))
            except CdpError:
                # The browser would not open or attach a page: it is gone or stuck.
                return self.finish(browser_exit=True)
        return self.finish()


if __name__ == "__main__":
    try:
        Check(sys.argv[1], sys.argv[2], app=len(sys.argv) > 3 and sys.argv[3] == "app").run()
    except Exception:  # noqa: BLE001 - the gateway reads "no result"
        os._exit(0)
