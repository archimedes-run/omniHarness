"""The react pre-build (Spec 012 FR-017, Slice 2): sources to one document.

No compile in the frame and no eval: the gateway writes the model's sources
and its OWN build files (package.json with pinned versions, the entry that
mounts the component) into a fresh, unguessable folder in the chat's
sandbox, and runs npm and esbuild there by absolute path with a fixed PATH,
a clean environment (only the registries proxy and its CA are passed on),
`--ignore-scripts` (no package install script runs) and a hard stop of
caps.REACT_BUILD_SECONDS. esbuild bundles; it runs none of the model's code.

The output is read back by the gateway, never trusted: each file must be a
regular file (not a link) under its cap, read through `head -c cap+1` so a
file that grows is refused, never truncated; then `frame.react_files_to_html`
inlines it with the Apps inliner (caps first, a linear tokenizer, local
files only) and scans it. A failed build is reported with the log tail
(the compiler's words about the model's code: shown and given to the model
only fenced, as data).
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.gateway.artifacts_store import caps, frame
from app.gateway.artifacts_store.kinds import Canonical, InvalidContent, TooLarge

logger = logging.getLogger(__name__)

B = "/usr/bin"
NODE_BIN = "/opt/nodejs/22/bin"
#: Pinned: the build recipe is part of what a version records (and what
#: promotion after spec 008 will reuse).
VERSIONS = {"esbuild": "0.24.2", "react": "18.3.1", "react-dom": "18.3.1"}
ENTRY = "__omni_entry.jsx"
#: Environment passed through to npm (the sandbox's registries proxy and its CA).
PASS_ENV = ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "NO_PROXY", "no_proxy", "NODE_EXTRA_CA_CERTS")


def _q(text: str) -> str:
    return shlex.quote(text)


@dataclass
class BuildResult:
    ok: bool
    canon: Canonical | None = None
    findings: list[str] = field(default_factory=list)
    log: str = ""
    reason: str = ""
    recipe: dict = field(default_factory=dict)


def recipe(entry: str) -> dict:
    return {"tool": "esbuild", "versions": dict(VERSIONS), "entry": entry, "mount": "default export rendered into #root", "format": "iife", "jsx": "automatic", "minify": True, "install": "npm --ignore-scripts"}


#: The build's package.json and lockfile, tracked (react_kit/): `npm ci`
#: installs exactly these tarballs (integrity-checked), nothing resolved anew.
_KIT = Path(__file__).with_name("react_kit")
PACKAGE_LOCK = (_KIT / "package-lock.json").read_text(encoding="utf-8")


def package_json() -> str:
    return json.dumps({"name": "omni-artifact", "private": True, "version": "0.0.0", "dependencies": {"react": VERSIONS["react"], "react-dom": VERSIONS["react-dom"]}, "devDependencies": {"esbuild": VERSIONS["esbuild"]}}, indent=2)


def entry_module(entry: str) -> str:
    # `entry` passed frame.canonical_react_source's path rules: plain characters only.
    return f'import App from "./{entry}";\nimport {{ createElement }} from "react";\nimport {{ createRoot }} from "react-dom/client";\ncreateRoot(document.getElementById("root")).render(createElement(App));\n'


def command(directory: str) -> str:
    """npm install, then esbuild, under a hard stop. Output to build.log."""
    keep = " ".join(f'{name}="${{{name}:-}}"' for name in PASS_ENV)
    inner = (
        f"{NODE_BIN}/npm ci --no-audit --no-fund --ignore-scripts --loglevel=error >> build.log 2>&1 && "
        f"{NODE_BIN}/node ./node_modules/esbuild/bin/esbuild src/{ENTRY} --bundle --minify --format=iife --jsx=automatic --target=es2020 "
        "--loader:.js=jsx --define:process.env.NODE_ENV='\"production\"' --outfile=dist/app.js --log-level=error --log-limit=20 >> build.log 2>&1"
    )
    return (
        f'cd {_q(directory)} && {B}/env -i PATH={NODE_BIN}:/usr/bin:/bin HOME="${{HOME:-/tmp}}" LANG=C.UTF-8 npm_config_cache="${{HOME:-/tmp}}/.npm" {keep} '
        f"{B}/timeout -k 5 {caps.REACT_BUILD_SECONDS} /bin/sh -c {_q(inner)} < /dev/null; echo __exit=$?"
    )


def read_bytes(ops, path: str, cap: int) -> bytes | None:
    """The build output through the checks' capped read (one command, at most
    cap+1 bytes, a regular file, never a link)."""
    from app.gateway.artifacts_store.checks import capped_read

    return capped_read(ops, path, cap, timeout=60)


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _tail(text: str | None) -> str:
    clean = _ANSI.sub("", text or "")
    clean = "".join(c if c.isprintable() or c in "\n\t" else " " for c in clean)
    return clean[-caps.BUILD_LOG_CHARS :].strip()


def build(ops, source: dict, *, beat: Callable[[], None] | None = None) -> BuildResult:
    """Build `source` ({entry, files}, already canonical) in the sandbox."""
    entry = source["entry"]
    rec = recipe(entry)
    directory = f"/tmp/omni-artb-{secrets.token_hex(16)}"
    try:
        dirs = sorted({f"{directory}/src/{p.rsplit('/', 1)[0]}" for p in source["files"] if "/" in p})
        mk = " ".join(_q(d) for d in [f"{directory}/src", f"{directory}/dist", *dirs])
        _, made = ops.sh(f"{B}/mkdir -m 700 {_q(directory)} && {B}/mkdir -p {mk} && echo __made__", timeout=15)
        if "__made__" not in made:
            return BuildResult(False, reason="the build folder could not be made in the sandbox", recipe=rec)
        for path, text in source["files"].items():
            ops.write(f"{directory}/src/{path}", text)
        ops.write(f"{directory}/src/{ENTRY}", entry_module(entry))
        ops.write(f"{directory}/package.json", package_json())
        ops.write(f"{directory}/package-lock.json", PACKAGE_LOCK)
        if beat:
            beat()
        code, out = ops.sh(command(directory), timeout=caps.REACT_BUILD_SECONDS + 30)
        if beat:
            beat()
        exit_line = re.findall(r"__exit=(\d+)", out or "")
        status = int(exit_line[-1]) if exit_line else None
        log_raw = None
        try:
            _, log_raw = ops.sh(f"[ -f {_q(directory + '/build.log')} ] && [ ! -L {_q(directory + '/build.log')} ] && {B}/tail -c {caps.BUILD_LOG_CHARS} {_q(directory + '/build.log')}; true", timeout=15)
        except Exception:  # noqa: BLE001 - the log is shown, never evidence
            log_raw = ""
        log = _tail(log_raw)
        if status != 0:
            reason = f"the build stopped at its {caps.REACT_BUILD_SECONDS} s limit" if status in (124, 137) else "the build failed (see the log)"
            return BuildResult(False, log=log, reason=reason, recipe=rec)
        js = read_bytes(ops, f"{directory}/dist/app.js", caps.REACT_BUNDLE_BYTES)
        if js is None:
            return BuildResult(False, log=log, reason=f"the build output is missing, not a plain file, or larger than {caps.REACT_BUNDLE_BYTES} bytes", recipe=rec)
        css = read_bytes(ops, f"{directory}/dist/app.css", caps.REACT_BUNDLE_BYTES)
        try:
            canon, findings = frame.react_files_to_html(js, css)
        except (InvalidContent, TooLarge) as exc:
            return BuildResult(False, log=log, reason=f"the build output was refused: {exc}", recipe=rec)
        return BuildResult(True, canon=canon, findings=findings, log=log, recipe=rec)
    except Exception:  # noqa: BLE001 - the sandbox API failed
        logger.warning("react artifact build could not run", exc_info=True)
        return BuildResult(False, reason="the sandbox did not answer", recipe=rec)
    finally:
        try:
            ops.sh(f"{B}/rm -rf {_q(directory)}", timeout=30)
        except Exception:  # noqa: BLE001
            pass
