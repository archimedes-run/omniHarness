"""Downloads (Spec 012, save model): the attachment name and body per kind.

The name is built from the title only after every unsafe character is gone:
no path separators, no control, bidi or format characters, no leading dots, at
most 100 characters before the extension, never empty. The extension is the
kind's own; a title's own extension is kept only when it already matches (or,
for `file`, when it is a plain short extension). The header carries an ASCII
`filename` and the UTF-8 name as `filename*` (RFC 5987/6266).
"""

from __future__ import annotations

import io
import json
import re
import unicodedata
import zipfile
from urllib.parse import quote

from app.gateway.artifacts_store import blobs

NAME_CHARS = 100
CODE_EXTENSIONS = {
    "python": ".py", "javascript": ".js", "typescript": ".ts", "tsx": ".tsx", "jsx": ".jsx", "json": ".json", "css": ".css",
    "scss": ".scss", "bash": ".sh", "sh": ".sh", "shell": ".sh", "go": ".go", "rust": ".rs", "java": ".java", "kotlin": ".kt",
    "c": ".c", "cpp": ".cpp", "csharp": ".cs", "ruby": ".rb", "php": ".php", "swift": ".swift", "sql": ".sql", "yaml": ".yaml",
    "toml": ".toml", "xml": ".xml", "html": ".html", "markdown": ".md", "r": ".r", "lua": ".lua", "text": ".txt",
}  # fmt: skip
KIND_EXTENSIONS = {"markdown": ".md", "svg": ".svg", "mermaid": ".mmd", "chart": ".json", "webapp": ".zip", "html": ".html", "react": ".html"}
IMAGE_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')
_PLAIN_EXT = re.compile(r"^\.[A-Za-z0-9]{1,8}$")


def _clean(title: str) -> str:
    text = "".join(ch for ch in unicodedata.normalize("NFKC", str(title or "")) if unicodedata.category(ch) not in ("Cc", "Cf", "Zl", "Zp"))
    text = _UNSAFE.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip(" ._")
    return text


def extension(kind: str, meta: dict, data: bytes) -> str:
    if kind == "code":
        return CODE_EXTENSIONS.get(str(meta.get("language") or "text"), ".txt")
    if kind == "image":
        return IMAGE_EXTENSIONS.get(str(meta.get("media_type")), "")
    return KIND_EXTENSIONS.get(kind, "")


def filename(title: str, kind: str, meta: dict, data: bytes) -> str:
    """A safe file name with the kind's extension."""
    base = _clean(title) or "artifact"
    stem, dot, own = base.rpartition(".")
    own_ext = f".{own}" if dot and stem else ""
    ext = extension(kind, meta, data)
    if kind == "file":
        ext = own_ext if _PLAIN_EXT.match(own_ext) else ""
    if own_ext and own_ext.lower() == ext.lower():
        base = stem
    elif kind == "file" and ext:
        base = stem
    base = base[:NAME_CHARS].rstrip(" ._") or "artifact"
    return f"{base}{ext}"


def disposition(name: str) -> str:
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace("?", "_").replace('"', "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"


def body(kind: str, data: bytes) -> bytes:
    """The file's bytes: code downloads as its text, everything else as stored."""
    if kind == "code":
        return str(json.loads(data).get("text", "")).encode("utf-8")
    return data


def webapp_zip(store, owner_id: str, files: list[dict]) -> bytes:
    """A web app's file set as a .zip (paths as stored; they were checked on save)."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for f in files:
            archive.writestr(f["path"], blobs.read(owner_id, f["content_hash"]))
    return out.getvalue()
