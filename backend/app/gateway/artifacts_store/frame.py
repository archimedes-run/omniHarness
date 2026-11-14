"""Code kinds in the locked frame (Spec 012 Slice 2: FR-016, FR-017, FR-029 to FR-031).

`html` and `react` artifacts run ONLY in the locked frame: a document served
by the gateway at `/api/artifacts/{id}/versions/{n}/frame.html` under the
artifact profile (frame/profile.json), embedded with sandbox="allow-scripts"
exactly. The frame holds nothing: no bridge, no token, no data, no network,
no same-origin access, no navigation. That is why the artifact profile may
allow inline script (model HTML relies on inline handlers and innerHTML)
where the app profile hashes every script and turns Trusted Types on.

What this module decides, all in the gateway:

* `canonical_html` / `canonical_react_source`: the stored bytes of a version,
  checked (UTF-8, no NUL, caps, a linear parse) and SCANNED with the Apps
  scan (apps/bundle.py). Frame markup, `srcdoc`, the WebRTC constructors and
  XSLT are REFUSED: they are the only ways to a realm the shim never ran in,
  and the CSP cannot stop WebRTC. Everything else the scan knows (remote
  references, `@import`, `<meta http-equiv>`, `<base>`, WebSocket, eval)
  is a FINDING, reported to the model and shown: the frame has no network,
  so such an artifact only misrenders itself.
* `frame_document`: the stored document with the gateway's own shim
  (frame/artifact-shim.js) injected as its first script. Deterministic: the
  probe checks these exact bytes (their SHA-256 is recorded).
* `react_files_to_html`: a react build's output read back from the sandbox
  (gateway-written index.html, the bundle's app.js and app.css) inlined by
  the Apps inliner (`bundle.inline`: caps first, a linear tokenizer, local
  files only), then canonicalised like any html.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.gateway.apps import bundle
from app.gateway.artifacts_store import caps
from app.gateway.artifacts_store.kinds import Canonical, InvalidContent, TooLarge, dumps

_DIR = Path(__file__).with_name("frame")
PROFILE: dict = json.loads((_DIR / "profile.json").read_text(encoding="utf-8"))
#: The artifact profile's CSP (FR-031), exactly.
CSP: str = PROFILE["csp"]
#: Every other header of the frame document.
HEADERS: dict[str, str] = dict(PROFILE["headers"])
SANDBOX: str = PROFILE["sandbox"]
SHIM: str = (_DIR / "artifact-shim.js").read_text(encoding="utf-8")
SHIM_SHA256 = hashlib.sha256(SHIM.encode("utf-8")).hexdigest()

HTML_MEDIA_TYPE = "text/html"
REACT_MEDIA_TYPE = "text/html"
SOURCE_MEDIA_TYPE = "application/json"

#: React source rules (FR-030): {entry, files}.
REACT_MAX_FILES = 50
REACT_EXTENSIONS = (".tsx", ".ts", ".jsx", ".js", ".css", ".json")
_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}(/[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}){0,5}$")

#: Refused: a way to a realm without the shim (FR-018 of 011, kept for artifacts).
_REFUSED_API = (
    ("RTCPeerConnection", re.compile(r"RTCPeerConnection")),
    ("RTCDataChannel", re.compile(r"RTCDataChannel")),
    ("XSLTProcessor", re.compile(r"XSLTProcessor")),
)
#: Findings: blocked by the frame anyway; reported so the artifact can be fixed.
_FINDING_API = (
    ("WebSocket", re.compile(r"WebSocket")),
    ("EventSource", re.compile(r"EventSource")),
    ("eval", re.compile(r"(?<![\w$.])eval\s*\(")),
    ("new Function", re.compile(r"new\s+Function\b")),
    ("sendBeacon", re.compile(r"sendBeacon")),
    ("serviceWorker", re.compile(r"serviceWorker")),
)
MAX_FINDINGS = 12


def _check_text(value: Any, what: str) -> str:
    if not isinstance(value, str):
        raise InvalidContent(f"{what} must be text.")
    if "\x00" in value:
        raise InvalidContent(f"{what} contains a NUL character.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidContent(f"{what} is not valid UTF-8.") from None
    return value


def scan(html: str) -> list[str]:
    """Findings in fixed words (never an echo of the document), or
    InvalidContent for what is refused. Linear: the Apps tokenizer and
    literal patterns only."""
    try:
        tags = bundle._tags(html)  # noqa: SLF001 — the Apps tokenizer, reused on purpose
    except bundle.BundleError as exc:
        raise InvalidContent(f"the document cannot be read: {exc}") from None
    try:
        bundle._scan_frames(html)  # noqa: SLF001
    except bundle.BundleError:
        raise InvalidContent("it creates a frame (iframe, frame, object, embed, portal or srcdoc); artifacts cannot hold frames.") from None
    for name, pattern in _REFUSED_API:
        if pattern.search(html):
            raise InvalidContent(f"it names {name}, which artifacts may not use.")
    findings: list[str] = []

    def add(text: str) -> None:
        if text not in findings and len(findings) < MAX_FINDINGS:
            findings.append(text)

    for t in tags:
        if t.name == "meta" and t.attr("http-equiv") is not None:
            add("a <meta http-equiv> element (ignored in the frame)")
        if t.name == "base":
            add("a <base> element (ignored in the frame)")
        for aname, value, _, _ in t.attrs:
            if value is None or aname not in bundle._URL_ATTRS:  # noqa: SLF001
                continue
            ref = value.strip()
            if aname == "srcset" or bundle._is_remote(ref):  # noqa: SLF001
                if ref.lower().startswith(("javascript:", "mailto:")) or (t.name == "a" and aname == "href"):
                    continue  # links go through the host's "Open link?" dialog
                add(f"<{t.name[:20]} {aname}> loads from the network (blocked in the frame: use data: URLs)")
            elif ref and not ref.startswith("#") and not ref.lower().startswith(("data:", "blob:")) and not (t.name == "a" and aname == "href"):
                add(f"<{t.name[:20]} {aname}> names a file that is not in the artifact (it will not load)")
        if t.name == "style" and t.body:
            css = html[t.body[0] : t.body[1]]
            if bundle._CSS_IMPORT.search(css):  # noqa: SLF001
                add("a stylesheet uses @import (blocked in the frame)")
            try:
                for _, _, ref in bundle._css_urls(css):  # noqa: SLF001
                    if ref and not ref.startswith("#") and not ref.lower().startswith("data:"):
                        add("a stylesheet url() loads from outside the artifact (blocked in the frame: use data: URLs)")
                        break
            except bundle.BundleError:
                add("a stylesheet has an unclosed url()")
        style = t.attr("style")
        if style and "url(" in style.lower() and "url(data:" not in style.lower().replace(" ", "").replace('"', "").replace("'", ""):
            add("an inline style url() loads from outside the artifact (blocked in the frame)")
    for name, pattern in _FINDING_API:
        if pattern.search(html):
            add(f"the code names {name} (blocked in the frame: there is no network and no eval)")
    if re.search(r"\b(fetch|XMLHttpRequest)\s*\(|new\s+XMLHttpRequest", html):
        add("the code makes network requests (blocked in the frame: there is no network)")
    return findings


def canonical_html(content: Any) -> tuple[Canonical, list[str]]:
    """(stored bytes, findings) for an `html` version (FR-029)."""
    text = _check_text(content, "content")
    data = text.encode("utf-8")
    if len(data) > caps.TEXT_VERSION_BYTES:
        raise TooLarge(len(data), caps.TEXT_VERSION_BYTES)
    if not text.strip():
        raise InvalidContent("the document is empty.")
    findings = scan(text)
    return Canonical(data, HTML_MEDIA_TYPE, None, None), findings


def canonical_react_source(content: Any) -> tuple[bytes, dict]:
    """The canonical source blob of a `react` version (FR-030): JSON
    {"entry", "files"} with sorted keys. Returns (bytes, parsed)."""
    if isinstance(content, str):
        if len(content.encode("utf-8", "replace")) > caps.REACT_SOURCE_BYTES:
            raise TooLarge(len(content.encode("utf-8", "replace")), caps.REACT_SOURCE_BYTES)
        try:
            content = json.loads(content)
        except ValueError:
            raise InvalidContent('react content is {"entry": "App.tsx", "files": {"App.tsx": "..."}}.') from None
    if not isinstance(content, dict) or set(content) - {"entry", "files"} or not isinstance(content.get("files"), dict):
        raise InvalidContent('react content is {"entry": "App.tsx", "files": {"App.tsx": "..."}}.')
    files = content["files"]
    if not files or len(files) > REACT_MAX_FILES:
        raise InvalidContent(f"react content has 1 to {REACT_MAX_FILES} files.")
    clean: dict[str, str] = {}
    for path, text in files.items():
        if not isinstance(path, str) or not _PATH.fullmatch(path) or ".." in path.split("/") or path.startswith("__omni") or not path.endswith(REACT_EXTENSIONS):
            raise InvalidContent(f"file names are short relative paths ending in {', '.join(REACT_EXTENSIONS)} (no .. or leading /).")
        clean[path] = _check_text(text, "a file")
    entry = content.get("entry")
    if entry is None:
        entry = next((p for p in ("App.tsx", "App.jsx", "index.tsx", "main.tsx", "App.ts", "App.js") if p in clean), None)
    if not isinstance(entry, str) or entry not in clean or not entry.endswith((".tsx", ".jsx", ".ts", ".js")):
        raise InvalidContent("entry must name one of the files (a .tsx, .jsx, .ts or .js file).")
    value = {"entry": entry, "files": clean}
    data = dumps(value)
    if len(data) > caps.REACT_SOURCE_BYTES:
        raise TooLarge(len(data), caps.REACT_SOURCE_BYTES)
    for name, pattern in _REFUSED_API:
        if any(pattern.search(t) for t in clean.values()):
            raise InvalidContent(f"the source names {name}, which artifacts may not use.")
    return data, value


def source_of(data: bytes) -> dict:
    return json.loads(data)


def frame_document(stored: bytes) -> bytes:
    """The exact document the frame route serves for a stored version: the
    gateway's shim first. Deterministic (the probe hashes these bytes)."""
    return bundle.inject_first(stored.decode("utf-8"), SHIM).encode("utf-8")


def frame_sha256(document: bytes) -> str:
    """SHA-256 of the frame document served for `document` (a version's
    stored_document)."""
    return hashlib.sha256(frame_document(document)).hexdigest()


REACT_INDEX = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
    '<title>Artifact</title><link rel="stylesheet" href="app.css"></head><body><div id="root"></div><script src="app.js"></script></body></html>'
)


def react_files_to_html(js: bytes, css: bytes | None) -> tuple[Canonical, list[str]]:
    """A react build's output, inlined by the Apps inliner into one document
    (no shim: the frame route adds the artifact shim when it serves it)."""
    files = {bundle.ENTRY: REACT_INDEX.encode("utf-8"), "app.js": js, "app.css": css or b""}
    if sum(len(v) for v in files.values()) > caps.REACT_BUNDLE_BYTES:
        raise TooLarge(sum(len(v) for v in files.values()), caps.REACT_BUNDLE_BYTES)
    try:
        html, _ = bundle.inline(files, platform_shim="", forbid=False)
    except bundle.BundleError as exc:
        raise InvalidContent(f"the build output does not inline into one document ({exc.code})") from None
    html = html.replace(b"<script></script>", b"", 1)
    if len(html) > caps.REACT_BUNDLE_BYTES:
        raise TooLarge(len(html), caps.REACT_BUNDLE_BYTES)
    text = html.decode("utf-8")
    findings = scan(text)
    return Canonical(html, REACT_MEDIA_TYPE, None, None), findings


# -- webapp: a stored static file set (Slice 2, owner update) -------------------------
#
# A `webapp` version is ONE canonical blob: JSON {"entry": "index.html",
# "files": {"<path>": "<base64>"}} (sorted keys), at most WEBAPP_MAX_FILES
# files and caps.WEBAPP_FILES_BYTES decoded. Immutable like any version.
# A page of it is served by the frame route by relative path: the gateway
# inlines THAT html page with its local assets (the Apps inliner: local files
# only, caps, a linear tokenizer) into one self-contained document under the
# same artifact profile. Nothing else of the set is ever served to the frame
# (the CSP has no 'self'): no network, as for html and react.

WEBAPP_MAX_FILES = 300
WEBAPP_PAGE = (".html", ".htm")
_WEBAPP_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.@+-]{0,99}(/[A-Za-z0-9_][A-Za-z0-9_.@+-]{0,99}){0,9}$")


def check_path(path: Any) -> str:
    """A relative path inside a stored set, or InvalidContent: plain
    segments only (no '..', no leading '/', no backslash, no empty or dot
    segment, no control characters), at most 10 deep."""
    if not isinstance(path, str) or not _WEBAPP_PATH.fullmatch(path) or any(seg in ("", ".", "..") or seg.endswith(".") for seg in path.split("/")):
        raise InvalidContent("file paths are plain relative paths (letters, digits, _ . @ + -), no .. and no leading /.")
    return path


def canonical_webapp(files: dict[str, bytes], entry: str = "index.html") -> tuple[Canonical, list[str]]:
    """(stored bytes, findings) for a `webapp` version from a file set
    (path -> bytes, e.g. a coding job's published folder). The entry page
    must inline into one document; the scan refuses frames and WebRTC."""
    import base64

    if not isinstance(files, dict) or not files or len(files) > WEBAPP_MAX_FILES:
        raise InvalidContent(f"a web app has 1 to {WEBAPP_MAX_FILES} files.")
    total = 0
    clean: dict[str, str] = {}
    for path, data in files.items():
        check_path(path)
        if not isinstance(data, bytes | bytearray):
            raise InvalidContent("file contents are bytes.")
        total += len(data)
        if total > caps.WEBAPP_FILES_BYTES:
            raise TooLarge(total, caps.WEBAPP_FILES_BYTES)
        clean[path] = base64.b64encode(bytes(data)).decode("ascii")
    check_path(entry)
    if entry not in clean or not entry.lower().endswith(WEBAPP_PAGE):
        raise InvalidContent("entry must name an .html file of the set.")
    data = dumps({"entry": entry, "files": clean})
    page = webapp_page(data, entry)
    return Canonical(data, "application/json", None, None), scan(page.decode("utf-8"))


def webapp_set(stored: bytes) -> tuple[str, dict[str, bytes]]:
    import base64

    value = json.loads(stored)
    return value["entry"], {p: base64.b64decode(b) for p, b in value["files"].items()}


def webapp_page(stored: bytes, path: str | None = None) -> bytes:
    """One html page of a stored set, inlined (no shim), or InvalidContent."""
    entry, files = webapp_set(stored)
    path = check_path(path) if path is not None else entry
    if path not in files or not path.lower().endswith(WEBAPP_PAGE):
        raise InvalidContent("no such page in this web app.")
    try:
        html, _ = bundle.inline(files, entry=path, platform_shim="", forbid=False)
    except bundle.BundleError as exc:
        raise InvalidContent(f"the page does not inline into one document ({exc.code})") from None
    html = html.replace(b"<script></script>", b"", 1)
    scan(html.decode("utf-8"))  # refusals hold for every page served
    return html


def stored_document(kind: str, stored: bytes, path: str | None = None) -> bytes:
    """The document a code version shows (before the shim): html and react
    their stored document (no path), webapp the inlined page at `path`
    (default: its entry)."""
    if kind == "webapp":
        return webapp_page(stored, path)
    if path is not None:
        raise InvalidContent("only a web app has pages.")
    return stored


def download_page(kind: str, stored: bytes) -> bytes:
    """The built page to download: the document with a network-blocking CSP
    meta tag first in <head> (a saved copy has no network either)."""
    meta = "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:\">"
    html = stored_document(kind, stored).decode("utf-8")
    m = re.search(r"<head[^>]*>", html[:4096], re.I)
    out = html[: m.end()] + meta + html[m.end() :] if m else meta + html
    return out.encode("utf-8")


def source_files(kind: str, stored: bytes, source: bytes | None) -> dict[str, bytes]:
    """The source files for the .zip: html its document, react its files,
    webapp its set. Every name passed the path rules when it was stored and
    is checked again here."""
    if kind == "html":
        return {"index.html": stored}
    if kind == "react":
        value = json.loads(source or b"{}")
        out = {check_path(p): t.encode("utf-8") for p, t in (value.get("files") or {}).items()}
        return out
    _, files = webapp_set(stored)
    return {check_path(p): b for p, b in files.items()}
