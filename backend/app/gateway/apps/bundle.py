"""An app's bundle: inlined into one self-contained document, scanned, and
served with the exact CSP of Spec 011 FR-016 (FR-018, FR-028).

The CSP and the sandbox are the controls. Inlining and the scan are defence in
depth and make failures early and legible: a bundle that would need the
network (a remote script, style, image or font) or names an API the platform
removes (WebRTC, WebSocket, eval, new Function) is refused at registration.
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import posixpath
import re
from pathlib import Path

BUNDLE_MAX_BYTES = 2 * 1024 * 1024
ENTRY = "index.html"


class BundleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


#: Names the platform shim removes or the CSP cannot govern (FR-018).
FORBIDDEN = (
    ("RTCPeerConnection", re.compile(r"RTCPeerConnection")),
    ("RTCDataChannel", re.compile(r"RTCDataChannel")),
    ("WebSocket", re.compile(r"WebSocket")),
    ("eval", re.compile(r"(?<![\w$.])eval\s*\(")),
    ("new Function", re.compile(r"new\s+Function\b")),
)

_SCRIPT_SRC = re.compile(r"<script\b([^>]*?)\bsrc\s*=\s*([\"'])(.*?)\2([^>]*)>\s*</script\s*>", re.IGNORECASE | re.DOTALL)
_STYLESHEET = re.compile(r"<link\b(?=[^>]*\brel\s*=\s*([\"'])stylesheet\1)[^>]*?\bhref\s*=\s*([\"'])(.*?)\2[^>]*>", re.IGNORECASE | re.DOTALL)
_INLINE_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
_URL_ATTR = re.compile(r"\b(src|href|srcset|poster|action|formaction|data|xlink:href)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE | re.DOTALL)
_CSS_URL = re.compile(r"url\(\s*([\"']?)(.*?)\1\s*\)", re.IGNORECASE)
_CSS_IMPORT = re.compile(r"@import\b", re.IGNORECASE)
_META_REFRESH = re.compile(r"<meta\b[^>]*http-equiv", re.IGNORECASE)
_BASE = re.compile(r"<base\b", re.IGNORECASE)
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

CSP_TEMPLATE = (
    "sandbox allow-scripts; default-src 'none'; script-src {scripts}; style-src 'unsafe-inline'; "
    "img-src data: blob:; font-src data:; media-src 'none'; connect-src 'none'; frame-src 'none'; "
    "child-src 'none'; worker-src 'none'; object-src 'none'; manifest-src 'none'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'self'"
)

#: Headers every app document is served with besides its CSP (FR-016).
STATIC_HEADERS = {
    "Cache-Control": "private, max-age=31536000, immutable",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-DNS-Prefetch-Control": "off",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), clipboard-read=(), clipboard-write=()",
}


def csp(script_hashes: list[str]) -> str:
    scripts = " ".join(f"'sha256-{h}'" for h in script_hashes) or "'none'"
    return CSP_TEMPLATE.format(scripts=scripts)


def _resolve(files: dict[str, bytes], ref: str, base: str = "") -> bytes:
    ref = ref.split("#", 1)[0].split("?", 1)[0]
    path = posixpath.normpath(posixpath.join(posixpath.dirname(base), ref.lstrip("/"))) if not ref.startswith("/") else posixpath.normpath(ref.lstrip("/"))
    if path.startswith("..") or path not in files:
        raise BundleError("missing_file", f"the bundle has no file {ref!r}")
    return files[path]


def _is_remote(ref: str) -> bool:
    ref = ref.strip()
    return ref.startswith("//") or (bool(_SCHEME.match(ref)) and not ref.lower().startswith("data:"))


def _data_uri(path: str, data: bytes) -> str:
    kind = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return f"data:{kind};base64,{base64.b64encode(data).decode()}"


def _inline_css(css: str, files: dict[str, bytes], base: str) -> str:
    if _CSS_IMPORT.search(css):
        raise BundleError("remote_url", "a stylesheet uses @import; inline it instead")

    def url(m: re.Match) -> str:
        ref = m.group(2).strip()
        if ref.lower().startswith("data:") or ref.startswith("#"):
            return m.group(0)
        if _is_remote(ref):
            raise BundleError("remote_url", f"a stylesheet loads {ref[:80]!r} from the network")
        return f'url("{_data_uri(ref, _resolve(files, ref, base))}")'

    return _CSS_URL.sub(url, css)


#: The platform shim (Spec 011 FR-018, FR-023): a byte copy of
#: frontend/src/core/apps/shim/omni-shim.js (a test keeps the two identical),
#: inlined by registration as the FIRST script of every app. The worker never
#: writes or edits it.
PLATFORM_SHIM_PATH = Path(__file__).with_name("kit") / "omni-shim.js"
_HEAD = re.compile(r"<head\b[^>]*>", re.IGNORECASE)
_HTML = re.compile(r"<html\b[^>]*>", re.IGNORECASE)


def platform_shim() -> str:
    return PLATFORM_SHIM_PATH.read_text(encoding="utf-8")


def with_prelude(html: str, prelude: str) -> str:
    """`prelude` as the document's first script: before anything in <head>."""
    tag = "<script>" + prelude.replace("</script", "<\\/script") + "</script>"
    for pattern in (_HEAD, _HTML):
        m = pattern.search(html)
        if m:
            return html[: m.end()] + tag + html[m.end() :]
    return tag + html


def inline(files: dict[str, bytes], entry: str = ENTRY, *, prelude: str | None = None) -> tuple[bytes, list[str]]:
    """(the self-contained document, its script hashes) or BundleError.

    `prelude` (the platform shim) is added as the first script AFTER the scan:
    it is the platform's own code, which names the APIs it removes."""
    if entry not in files:
        raise BundleError("missing_file", f"the bundle has no {entry}")
    try:
        html = files[entry].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleError("invalid_bundle", f"{entry} is not UTF-8") from exc
    if _META_REFRESH.search(html) or _BASE.search(html):
        raise BundleError("remote_url", "the document uses <meta http-equiv> or <base>")

    def script(m: re.Match) -> str:
        ref = m.group(3)
        if _is_remote(ref):
            raise BundleError("remote_url", f"a script loads {ref[:80]!r} from the network")
        text = _resolve(files, ref, entry).decode("utf-8", errors="strict").replace("</script", "<\\/script")
        attrs = " ".join(a.strip() for a in (m.group(1), m.group(4)) if a.strip())
        return f"<script{' ' + attrs if attrs else ''}>{text}</script>"

    def stylesheet(m: re.Match) -> str:
        ref = m.group(3)
        if _is_remote(ref):
            raise BundleError("remote_url", f"a stylesheet loads {ref[:80]!r} from the network")
        css = _inline_css(_resolve(files, ref, entry).decode("utf-8"), files, ref)
        return f"<style>{css}</style>"

    html = _SCRIPT_SRC.sub(script, html)
    html = _STYLESHEET.sub(stylesheet, html)

    def attr(m: re.Match) -> str:
        name, quote, ref = m.group(1), m.group(2), m.group(3).strip()
        if not ref or ref.startswith("#") or ref.lower().startswith(("data:", "blob:")):
            return m.group(0)
        if name.lower() == "srcset" or _is_remote(ref) or ref.lower().startswith("javascript:"):
            raise BundleError("remote_url", f"{name}={ref[:80]!r} is not inline")
        return f"{name}={quote}{_data_uri(ref, _resolve(files, ref, entry))}{quote}"

    # Markup only: script text is code, not attributes (a template literal
    # building `href="${url}"` is not a file reference). The CSP governs it.
    scripts: list[str] = []

    def keep(m: re.Match) -> str:
        scripts.append(m.group(0))
        return f"\x00{len(scripts) - 1}\x00"

    markup = _INLINE_SCRIPT.sub(keep, html)
    markup = _URL_ATTR.sub(attr, markup)
    markup = re.sub(r"<style\b([^>]*)>(.*?)</style\s*>", lambda m: f"<style{m.group(1)}>{_inline_css(m.group(2), files, entry)}</style>", markup, flags=re.IGNORECASE | re.DOTALL)
    for m in re.finditer(r"\bstyle\s*=\s*([\"'])(.*?)\1", markup, re.IGNORECASE | re.DOTALL):
        for u in _CSS_URL.finditer(m.group(2)):
            ref = u.group(2).strip()
            if not ref.lower().startswith("data:") and not ref.startswith("#"):
                raise BundleError("remote_url", f"an inline style loads {ref[:80]!r}")
    html = re.sub(r"\x00(\d+)\x00", lambda m: scripts[int(m.group(1))], markup)
    for name, pattern in FORBIDDEN:
        if pattern.search(html):
            raise BundleError("forbidden_api", f"the bundle names {name}, which apps may not use")
    if prelude is not None:
        html = with_prelude(html, prelude)
    hashes = []
    for m in _INLINE_SCRIPT.finditer(html):
        if re.search(r"\bsrc\s*=", m.group(1), re.IGNORECASE):
            raise BundleError("remote_url", "a script still has a src")
        hashes.append(base64.b64encode(hashlib.sha256(m.group(2).encode("utf-8")).digest()).decode())
    data = html.encode("utf-8")
    if len(data) > BUNDLE_MAX_BYTES:
        raise BundleError("bundle_too_large", f"the bundle is {len(data)} bytes after inlining; the limit is {BUNDLE_MAX_BYTES}")
    return data, list(dict.fromkeys(hashes))
