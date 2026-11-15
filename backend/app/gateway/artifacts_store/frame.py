"""Code kinds in the locked frame (Spec 012 Slice 2: FR-016, FR-017, FR-029 to FR-031).

`html`, `react` and `webapp` artifacts run ONLY in the locked frame: a
document served by the gateway at `/api/artifacts/{id}/versions/{n}/frame.html`,
embedded with sandbox="allow-scripts" exactly, under the SAME strict profile
as Apps (apps/bundle.py `csp()`): each inline script allowed by its SHA-256
hash and nothing else, Trusted Types with no policy (no HTML or script from
strings), no network, no frames, no workers, no forms.

What this module decides, all in the gateway:

* `canonical_html` / `canonical_react_source`: the stored bytes of a version,
  checked (UTF-8, no NUL, caps, a linear parse) and SCANNED. Frame markup,
  `srcdoc`, the WebRTC constructors and XSLT are REFUSED. What the strict
  profile will not run (inline event handlers, `javascript:` URLs, HTML from
  strings, strings as code) is a BLOCKING finding: stored, reported, and it
  fails the system check with that reason. Network references are findings.
* `frame_document`: the gateway's own shim (frame/artifact-shim.js) PREPENDED
  as the first bytes after the doctype (never placed by parsing the
  document), and the hashes of the inline scripts for the CSP. A script the
  tokenizer does not see gets no hash, so it does not run.
* `react_files_to_html`: a react build's output inlined by the Apps inliner.
* `webapp_pages`: every page of a stored file set inlined ONCE, at save time,
  each from only the files it references, under the inliner's cap; the frame
  route serves the stored result and never inlines on request.
"""

from __future__ import annotations

import base64
import hashlib
import json
import posixpath
import re
from pathlib import Path
from typing import Any

from app.gateway.apps import bundle
from app.gateway.artifacts_store import caps
from app.gateway.artifacts_store.kinds import Canonical, InvalidContent, TooLarge, dumps

_DIR = Path(__file__).with_name("frame")
PROFILE: dict = json.loads((_DIR / "profile.json").read_text(encoding="utf-8"))
#: The frame's headers besides its CSP.
HEADERS: dict[str, str] = dict(PROFILE["headers"])
SHIM: str = (_DIR / "artifact-shim.js").read_text(encoding="utf-8")
_SHIM_BODY = SHIM.replace("</script", "<\\/script")
SHIM_HASH = base64.b64encode(hashlib.sha256(_SHIM_BODY.encode("utf-8")).digest()).decode()

HTML_MEDIA_TYPE = "text/html"
REACT_MEDIA_TYPE = "text/html"

#: React source rules (FR-030): {entry, files}.
REACT_MAX_FILES = 50
REACT_EXTENSIONS = (".tsx", ".ts", ".jsx", ".js", ".css", ".json")
#: Packages a react source may import (the build installs only these).
REACT_PACKAGES = ("react", "react-dom", "react/jsx-runtime", "react-dom/client")
_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}(/[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}){0,5}$")
_IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*|@import\s+(?:url\()?\s*)(['"])([^'"\n]{0,300})\1""")

#: Refused: a way to a realm without the shim.
_REFUSED_API = (
    ("RTCPeerConnection", re.compile(r"RTCPeerConnection")),
    ("RTCDataChannel", re.compile(r"RTCDataChannel")),
    ("XSLTProcessor", re.compile(r"XSLTProcessor")),
)
#: The prefix of a finding the strict profile will not run: it fails the check.
BLOCKING = "Will not run in the frame: "
_SINKS = re.compile(r"\.(?:innerHTML|outerHTML)\s*\+?=|insertAdjacentHTML\s*\(|document\.write(?:ln)?\s*\(|createContextualFragment|setHTMLUnsafe|parseHTMLUnsafe|\bDOMParser\b")
_STRING_CODE = re.compile(r"(?<![\w$.])eval\s*\(|new\s+Function\b|set(?:Timeout|Interval)\s*\(\s*['\"`]")
SINK_WORDS = BLOCKING + "it writes HTML from strings (innerHTML, outerHTML, insertAdjacentHTML, document.write): build the page with DOM calls (createElement, append) and textContent"
HANDLER_WORDS = BLOCKING + "it uses inline event handlers (on... attributes): attach them with addEventListener in a <script> block"
JS_URL_WORDS = BLOCKING + "it uses javascript: URLs: use a button and addEventListener"
STRING_CODE_WORDS = BLOCKING + "it runs strings as code (eval, new Function, a string passed to setTimeout)"
SCRIPT_SRC_WORDS = BLOCKING + "a <script src> (only inline <script> blocks run)"
#: Findings: blocked by the frame anyway; reported so the artifact can be fixed.
_FINDING_API = (
    ("WebSocket", re.compile(r"WebSocket")),
    ("EventSource", re.compile(r"EventSource")),
    ("sendBeacon", re.compile(r"sendBeacon")),
    ("serviceWorker", re.compile(r"serviceWorker")),
)
MAX_FINDINGS = 12


def csp(script_hashes: list[str]) -> str:
    """The frame's CSP: the Apps profile, from the Apps builder (one profile)."""
    return bundle.csp(script_hashes)


def blocking(findings: list[str]) -> list[str]:
    return [f for f in findings if f.startswith(BLOCKING)]


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


def scan(html: str, *, code: bool = True) -> list[str]:
    """Findings in fixed words (never an echo of the document), or
    InvalidContent for what is refused. Linear: the Apps tokenizer and
    literal patterns only. `code=False` (a react bundle: React's own runtime
    holds the sink names and is safe under Trusted Types) skips the sink
    and string-code checks; the react SOURCE is checked instead."""
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
        if t.name == "script" and t.attr("src") is not None:
            add(SCRIPT_SRC_WORDS)
        for aname, value, _, _ in t.attrs:
            if aname.startswith("on") and len(aname) > 2:
                add(HANDLER_WORDS)
            if value is not None and re.sub(r"[\x00-\x20]", "", value).lower().startswith("javascript:"):
                add(JS_URL_WORDS)
            if value is None or aname not in bundle._URL_ATTRS:  # noqa: SLF001
                continue
            ref = value.strip()
            if ref.lower().startswith(("javascript:", "mailto:")) or (t.name == "a" and aname == "href") or (t.name == "script" and aname == "src"):
                continue  # links go through the host's "Open link?" dialog
            if aname == "srcset" or bundle._is_remote(ref):  # noqa: SLF001
                add(f"<{t.name[:20]} {aname}> loads from the network (blocked in the frame: use data: URLs)")
            elif ref and not ref.startswith("#") and not ref.lower().startswith(("data:", "blob:")):
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
    if code:
        if _SINKS.search(html):
            add(SINK_WORDS)
        if _STRING_CODE.search(html):
            add(STRING_CODE_WORDS)
    for name, pattern in _FINDING_API:
        if pattern.search(html):
            add(f"the code names {name} (blocked in the frame: there is no network)")
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


def _check_imports(path: str, text: str) -> None:
    """Imports stay inside the project: relative ones never climb above it;
    no absolute paths or URLs; bare ones are react only."""
    for m in _IMPORT.finditer(text):
        spec = m.group(2)
        if spec.startswith(("./", "../")):
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
            if target.startswith("..") or target.startswith("/"):
                raise InvalidContent("imports stay inside the project (no path above it).")
        elif spec.startswith("/") or ":" in spec or "\\" in spec:
            raise InvalidContent("imports are relative files of the project or react; no absolute paths or URLs.")
        elif spec not in REACT_PACKAGES:
            raise InvalidContent("only react and react-dom can be imported (no other packages).")


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
    if any("dangerouslySetInnerHTML" in t for t in clean.values()):
        raise InvalidContent("the source uses dangerouslySetInnerHTML, which the frame refuses: render with JSX.")
    for path, text in clean.items():
        _check_imports(path, text)
    return data, value


def react_source_findings(source: dict) -> list[str]:
    """What the strict profile will not run, in the model's own react code."""
    out: list[str] = []
    text = "\n".join(source["files"].values())
    if _SINKS.search(text):
        out.append(SINK_WORDS)
    if _STRING_CODE.search(text):
        out.append(STRING_CODE_WORDS)
    return out


# -- the frame document ---------------------------------------------------------------


def _doctype_end(html: str) -> int:
    """Where the first bytes after an optional leading doctype are (a BOM and
    whitespace before it allowed). Nothing else of the document is parsed."""
    i = 1 if html.startswith("﻿") else 0
    j = i
    while j < len(html) and html[j] in " \t\r\n\f":
        j += 1
    if html[j : j + 9].lower() == "<!doctype":
        close = html.find(">", j, j + 1024)
        if close >= 0:
            return close + 1
    return i


def prepend(html: str, markup: str) -> str:
    """`markup` as the very first content: right after the doctype if there
    is one, else at the very start (the parser puts it in <head>)."""
    at = _doctype_end(html)
    return html[:at] + markup + html[at:]


def script_hashes(html: str) -> list[str]:
    """The CSP hashes: the shim's, then each inline script the tokenizer
    finds. One it does not find has no hash and does not run (fail closed)."""
    out = [SHIM_HASH]
    try:
        tags = bundle._tags(html)  # noqa: SLF001
    except bundle.BundleError:
        return out
    for t in tags:
        if t.name == "script" and t.body and t.attr("src") is None:
            h = base64.b64encode(hashlib.sha256(html[t.body[0] : t.body[1]].encode("utf-8")).digest()).decode()
            if h not in out:
                out.append(h)
    return out


def frame_document(document: bytes) -> tuple[bytes, list[str]]:
    """The exact document the frame route serves (the shim prepended) and its
    script hashes. Deterministic: the probe checks these bytes."""
    html = prepend(document.decode("utf-8"), f"<script>{_SHIM_BODY}</script>")
    return html.encode("utf-8"), script_hashes(html)


def frame_sha256(document: bytes) -> str:
    return hashlib.sha256(frame_document(document)[0]).hexdigest()


REACT_INDEX = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
    '<title>Artifact</title><link rel="stylesheet" href="app.css"></head><body><div id="root"></div><script src="app.js"></script></body></html>'
)


def react_files_to_html(js: bytes, css: bytes | None) -> tuple[Canonical, list[str]]:
    """A react build's output, inlined by the Apps inliner into one document
    (no shim: the frame route prepends the artifact shim when it serves it)."""
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
    findings = scan(html.decode("utf-8"), code=False)
    return Canonical(html, REACT_MEDIA_TYPE, None, None), findings


# -- webapp: the save model's stored file set ------------------------------------------
#
# A `webapp` is saved by the owner ("Save to artifacts", service.import_from_chat)
# as an immutable file set (artifact_bundle_files). At save time every html page
# of it (up to WEBAPP_MAX_PAGES) is inlined ONCE from only the files that page
# references (so one page is bounded by the inliner's own cap whatever the size
# of the set), scanned and stored; the frame route serves the stored page and
# never inlines on the request path. Nothing else of the set reaches the frame.

WEBAPP_PAGE = (".html", ".htm")
WEBAPP_MAX_PAGES = 50


def _local(ref: str) -> bool:
    ref = ref.strip()
    return bool(ref) and not ref.startswith("#") and not ref.lower().startswith(("data:", "blob:", "javascript:", "mailto:")) and not bundle._is_remote(ref)  # noqa: SLF001


def _resolve(base: str, ref: str) -> str:
    ref = ref.split("#", 1)[0].split("?", 1)[0]
    return posixpath.normpath(ref.lstrip("/")) if ref.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(base), ref))


def _css_refs(css: str, base: str) -> list[str]:
    try:
        return [_resolve(base, ref) for _, _, ref in bundle._css_urls(css) if _local(ref)]  # noqa: SLF001
    except bundle.BundleError:
        return []


def page_subset(files: dict[str, bytes], page: str) -> dict[str, bytes]:
    """The page and only the files it (and its stylesheets) reference."""
    html = files[page].decode("utf-8")
    want = {page}
    for t in bundle._tags(html):  # noqa: SLF001
        for aname, value, _, _ in t.attrs:
            if aname in bundle._URL_ATTRS and value and _local(value) and not (t.name == "a" and aname == "href"):  # noqa: SLF001
                want.add(_resolve(page, value.strip()))
        if t.name == "style" and t.body:
            want.update(_css_refs(html[t.body[0] : t.body[1]], page))
    for path in [p for p in want if p.endswith(".css") and p in files]:
        want.update(_css_refs(files[path].decode("utf-8", "replace"), path))
    return {p: files[p] for p in want if p in files}


def _local_links_to_fragments(html: str) -> str:
    """`<a href="about.html">` inside a page becomes `href="#about.html"`: a
    link between pages of the set stays in the page (the host's page list
    switches pages), instead of the inliner embedding the other page."""
    out, at = [], 0
    for t in bundle._tags(html):  # noqa: SLF001
        if t.name != "a" and t.name != "area":
            continue
        for aname, value, vs, ve in t.attrs:
            if aname == "href" and value and _local(value) and not value.strip().startswith("#"):
                out += [html[at:vs], "#" + value.strip().replace('"', "").replace("'", "")]
                at = ve
    return "".join(out) + html[at:]


def webapp_pages(files: dict[str, bytes], entry: str) -> tuple[dict[str, bytes], dict[str, str], list[str]]:
    """({page: inlined document}, {page: why it cannot be shown}, findings)."""
    pages = sorted(p for p in files if p.lower().endswith(WEBAPP_PAGE))
    pages = ([entry] if entry in pages else []) + [p for p in pages if p != entry]
    done: dict[str, bytes] = {}
    failed: dict[str, str] = {}
    findings: list[str] = []
    for i, page in enumerate(pages):
        if i >= WEBAPP_MAX_PAGES:
            failed[page] = f"only the first {WEBAPP_MAX_PAGES} pages of a web app are prepared"
            continue
        try:
            files_for_page = {**files, page: _local_links_to_fragments(files[page].decode("utf-8")).encode("utf-8")}
            subset = page_subset(files_for_page, page)
            if sum(len(v) for v in subset.values()) > bundle.BUNDLE_MAX_BYTES:
                raise InvalidContent(f"the page and its files are over {bundle.BUNDLE_MAX_BYTES} bytes")
            html, _ = bundle.inline(subset, entry=page, platform_shim="", forbid=False)
            html = html.replace(b"<script></script>", b"", 1)
            for f in scan(html.decode("utf-8")):
                if f not in findings:
                    findings.append(f)
            done[page] = html
        except (InvalidContent, TooLarge, bundle.BundleError, UnicodeDecodeError) as exc:
            failed[page] = (str(exc) or "it cannot be shown")[:200]
    return done, failed, findings[:MAX_FINDINGS]


# -- downloads --------------------------------------------------------------------------

DOWNLOAD_META = "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:\">"


def download_page(document: bytes) -> bytes:
    """The built page to keep: a restrictive policy prepended by the gateway
    (first after the doctype), so a saved copy runs under it."""
    return prepend(document.decode("utf-8"), DOWNLOAD_META).encode("utf-8")


def source_files(kind: str, stored: bytes, source: bytes | None) -> dict[str, bytes]:
    """The sources for the .zip: html its document, react its files (names
    passed the path rules when stored and are checked again)."""
    if kind == "html":
        return {"index.html": stored}
    value = json.loads(source or b"{}")
    out = {}
    for p, t in (value.get("files") or {}).items():
        if not _PATH.fullmatch(p) or ".." in p.split("/"):
            raise InvalidContent("a source name is not a plain relative path.")
        out[p] = t.encode("utf-8")
    return out
