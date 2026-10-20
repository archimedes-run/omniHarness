"""Assemble the runtime image's Python packages as a tar (Feature 006, #59).

No pip download: ``mcp``, ``httpx`` and their dependency closure are copied
from an environment ``uv`` already installed from ``uv.lock`` with hashes,
and every copied file is checked against its distribution's ``RECORD``
sha256. Stdlib only, so it can run inside any Python 3.12 environment that
has the packages (the gateway, or a throwaway container of the gateway
image); it writes the tar to stdout when run as a script.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import sys
import tarfile
from importlib import metadata

ROOTS = ("mcp", "httpx")


class IntegrityError(RuntimeError):
    pass


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(req: str) -> str | None:
    """The distribution a requirement line needs here, or None if its marker
    rules it out (extras are never installed; Linux, CPython 3.12)."""
    head, _, marker = req.partition(";")
    marker = marker.strip()
    if marker:
        if "extra" in marker:
            return None
        env = {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix", "implementation_name": "cpython", "platform_python_implementation": "CPython"}
        m = marker.replace('"', "'")
        for k, v in env.items():
            m = re.sub(rf"\b{k}\b", repr(v), m)
        m = re.sub(r"\bpython_full_version\b", "'3.12.0'", m)
        m = re.sub(r"\bpython_version\b", "'3.12'", m)
        m = re.sub(r"\bplatform_machine\b", "'aarch64'", m)
        try:
            ok = _eval_marker(m)
        except Exception:
            ok = True  # keep it: a missing package fails loudly, an extra one does not
        if not ok:
            return None
    name = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", head)
    return _norm(name.group(1)) if name else None


def _eval_marker(expr: str) -> bool:
    def ver(v: str) -> tuple:
        return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.]", v))

    def cmp(a: str, op: str, b: str) -> bool:
        x, y = (ver(a), ver(b)) if re.fullmatch(r"[0-9.]+", a) and re.fullmatch(r"[0-9.]+", b) else (a, b)
        return {"==": x == y, "!=": x != y, "<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]

    def atom(m: re.Match) -> str:
        return str(cmp(m.group(1), m.group(2), m.group(3)))

    expr = re.sub(r"'([^']*)'\s*(==|!=|<=|>=|<|>)\s*'([^']*)'", atom, expr)
    expr = re.sub(r"'([^']*)'\s*(not in|in)\s*'([^']*)'", lambda m: str((m.group(1) in m.group(3)) if m.group(2) == "in" else (m.group(1) not in m.group(3))), expr)
    if not re.fullmatch(r"[\sTrueFalsandorn()]*", expr):
        raise ValueError(expr)
    return bool(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 - only True/False/and/or/not remain


def closure(roots=ROOTS) -> list[metadata.Distribution]:
    seen: dict[str, metadata.Distribution] = {}
    todo = [_norm(r) for r in roots]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        dist = metadata.distribution(name)
        seen[name] = dist
        for req in dist.requires or []:
            dep = _requirement_name(req)
            if dep and dep not in seen:
                todo.append(dep)
    return sorted(seen.values(), key=lambda d: _norm(d.metadata["Name"]))


def _check(dist: metadata.Distribution, rel, data: bytes) -> None:
    if rel.hash is None:
        return  # RECORD itself, INSTALLER, etc.: no hash by design
    if rel.hash.mode != "sha256":
        raise IntegrityError(f"{rel}: unsupported hash {rel.hash.mode}")
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    if digest != rel.hash.value:
        raise IntegrityError(f"{dist.metadata['Name']}: {rel} does not match its RECORD hash")


def assemble(roots=ROOTS) -> tuple[bytes, dict[str, str]]:
    """(tar bytes under ``site-packages/``, {distribution: version})."""
    buf = io.BytesIO()
    versions: dict[str, str] = {}
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for dist in closure(roots):
            versions[dist.metadata["Name"]] = dist.version
            for rel in dist.files or []:
                parts = rel.parts
                if "__pycache__" in parts or str(rel).endswith(".pyc") or parts[0] == ".." or rel.is_absolute():
                    continue
                path = dist.locate_file(rel)
                try:
                    data = path.read_bytes()
                except (FileNotFoundError, IsADirectoryError):
                    continue
                _check(dist, rel, data)
                info = tarfile.TarInfo("site-packages/" + "/".join(parts))
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
        manifest = json.dumps({"python": f"{sys.version_info[0]}.{sys.version_info[1]}", "packages": versions}, sort_keys=True).encode()
        info = tarfile.TarInfo("packages.json")
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))
    return buf.getvalue(), versions


if __name__ == "__main__":
    data, _ = assemble()
    sys.stdout.buffer.write(data)
