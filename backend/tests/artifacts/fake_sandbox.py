"""A fake of the chat's sandbox for code artifacts (Slice 2): it plays the
commands the gateway sends (mkdir, the layout probe, stat/head/base64 reads,
the react build) over an in-memory filesystem, so builds and checks run
through the real gateway code. The probe's answer is scripted per test."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shlex

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WIDTHS = (360, 560, 1280)


def page(width, **over):
    return {"width": width, "overflow_px": 0, "client_width": width, "offenders": [], "rendered": True, "svgs": [], **over}


class FakeSandbox:
    container = "fake"

    def __init__(self, *, probe=None, build=None):
        self.files: dict[str, str | bytes] = {}
        self.links: set[str] = set()
        #: path -> the size `stat` reports (a file that grows after the check)
        self.stat_size: dict[str, int] = {}
        self.commands: list[str] = []
        #: probe(check: dict, document: str) -> (exit code, result dict or raw str or None)
        self.probe = probe or (lambda check, doc: (0, passing(check, doc)))
        #: build(files: dict) -> (exit code, {path: content}, log)
        self.build = build or (lambda files: (0, {"dist/app.js": 'document.getElementById("root").textContent="hi";', "dist/app.css": "body{margin:0}"}, ""))
        self.closed = False

    def close(self):
        self.closed = True

    def touch(self):
        pass

    def write(self, path, content):
        self.files[path] = content

    def read_text(self, path):
        value = self.files.get(path)
        return value.decode() if isinstance(value, bytes) else value

    def _bytes(self, path):
        value = self.files.get(path)
        return value.encode() if isinstance(value, str) else value

    def sh(self, command, *, timeout=30):
        self.commands.append(command)
        if "__made__" in command and "mkdir -m 700" in command:
            return 0, "__made__"
        if "layout_probe.py" in command and "sha256sum" in command:
            directory = shlex.split(command.split("cd ", 1)[1])[0]
            check = json.loads(self.files[f"{directory}/check.json"])
            doc = self.files[f"{directory}/www/prod/index.html"]
            code, result = self.probe(check, doc)
            if result is not None:
                self.files[f"{directory}/result.json"] = result if isinstance(result, str) else json.dumps(result)
                for shot in (result.get("shots") if isinstance(result, dict) else None) or []:
                    if shot.get("file"):
                        self.files[f"{directory}/{shot['file']}"] = PNG
            return code, ""
        if "npm install" in command:
            directory = shlex.split(command.split("cd ", 1)[1])[0]
            src = {p[len(directory) + 5 :]: c for p, c in self.files.items() if p.startswith(directory + "/src/")}
            code, out, log = self.build(src)
            for rel, content in out.items():
                self.files[f"{directory}/{rel}"] = content
            self.files[f"{directory}/build.log"] = log
            return 0, f"__exit={code}"
        m = re.search(r"\[ -f (\S+) \] && \[ ! -L \S+ \] && /usr/bin/stat -c %s", command)
        if m:
            path = shlex.split(m.group(1))[0]
            if path in self.links or path not in self.files:
                return 0, "none"
            return 0, str(self.stat_size.get(path, len(self._bytes(path))))
        m = re.search(r"\[ -f (\S+) \] && \[ ! -L \S+ \] && /usr/bin/head -c (\d+) \S+ \| /usr/bin/base64 -w0 > (\S+)", command)
        if m:
            path, n, tmp = shlex.split(m.group(1))[0], int(m.group(2)), shlex.split(m.group(3))[0]
            if path in self.files and path not in self.links:
                self.files[tmp] = base64.b64encode(self._bytes(path)[:n]).decode()
            return 0, ""
        m = re.search(r"/usr/bin/tail -c (\d+) ([^\s;]+)", command)
        if m:
            path = shlex.split(m.group(2))[0]
            return 0, self.read_text(path) or ""
        if "/usr/bin/rm -" in command:
            for target in shlex.split(command.split("rm -", 1)[1])[1:]:
                for key in [k for k in self.files if k == target or k.startswith(target + "/")]:
                    del self.files[key]
            return 0, ""
        return 0, ""


def passing(check, doc, **over):
    """The probe's answer for THIS run (its nonce, the sha of the document it loaded)."""
    runs = [{"theme": t, "loaded": True, "crashed": False, "errors": 0, "first_error": "", "pages": [page(w) for w in WIDTHS], "violations": [], "watched": True, "blocked": 0} for t in ("light", "dark")]
    result = {
        "v": 1,
        "mode": "artifact",
        "widths": list(WIDTHS),
        "themes": ["light", "dark"],
        "runs": runs,
        "shots": [{"theme": t, "width": 1280, "file": f"shot-{t}-1280.png", "bytes": len(PNG), "height": 800} for t in ("light", "dark")],
        "nonce": check["nonce"],
        "prod_sha256": hashlib.sha256(doc.encode()).hexdigest(),
    }
    result.update(over)
    return result


def failing(**run_over):
    """A probe answer whose light run carries `run_over` (e.g. violations)."""

    def probe(check, doc):
        result = passing(check, doc)
        result["runs"][0].update(run_over)
        return 0, result

    return probe
