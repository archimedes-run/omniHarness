"""A request whose raw path uses an encoded or literal traversal or separator
trick never reaches the frontend: nginx answers 404 itself. Such a path can
leave /api/ once nginx normalises it (`/api/artifacts/..%2F..%2Fetc`), and the
frontend answered those with 500. Follow-up to Spec 012 S1."""

from __future__ import annotations

import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

NGINX_DIR = Path(__file__).resolve().parents[3] / "docker" / "nginx"
CONFS = ("nginx.conf", "nginx.local.conf")


@pytest.mark.parametrize("name", CONFS)
def test_every_shipped_config_answers_escaped_api_paths_itself(name):
    text = (NGINX_DIR / name).read_text()
    assert "map $request_uri $raw_path" in text and "map $raw_path $path_trick" in text, "the maps are missing"
    trick = text[text.index("map $raw_path $path_trick") :]
    trick = trick[: trick.index("}")]
    for needle in ("%2e", "%2f", "%5c", "//"):
        assert needle in trick, needle
    root = text[text.index("        location / {") :]
    root = root[: root.index("proxy_pass")]
    assert "if ($path_trick_answer = artifact)" in root and "artifact_not_found" in root and "if ($path_trick_answer = plain)" in root, "location / proxies trick paths"


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Stub(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = self.server.label.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _raw_get(port: int, path: str) -> tuple[int, str]:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode())
        data = b""
        while chunk := s.recv(65536):
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    return int(head.split()[1]), body.decode(errors="replace")


@pytest.mark.skipif(shutil.which("nginx") is None, reason="nginx is not installed here")
def test_the_local_config_really_answers_404(tmp_path):
    stubs = {}
    for label in ("gateway", "frontend"):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        server.label = label
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stubs[label] = server
    listen = _port()
    conf = (NGINX_DIR / "nginx.local.conf").read_text()
    conf = conf.replace("127.0.0.1:8001", f"127.0.0.1:{stubs['gateway'].server_port}").replace("127.0.0.1:3000", f"127.0.0.1:{stubs['frontend'].server_port}")
    conf = conf.replace("listen 127.0.0.1:2026;", f"listen 127.0.0.1:{listen};").replace("listen [::1]:2026;", "")
    (tmp_path / "logs").mkdir()
    (tmp_path / "nginx.conf").write_text(conf)
    proc = subprocess.Popen(["nginx", "-p", str(tmp_path), "-c", str(tmp_path / "nginx.conf"), "-g", "daemon off;"], stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", listen), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)
        status, body = _raw_get(listen, "/api/artifacts/..%2F..%2Fetc")
        assert status == 404 and "artifact_not_found" in body
        # Every spelling that leaves /api/ after normalising: never the frontend.
        for path in (
            "/api/models/..%2F..%2Fx",
            "//api/x/..%2F..%2Fy",
            "/./api/x/..%2F..%2Fy",
            "/%61pi/x/..%2F..%2Fy",
            "/%2Fapi/x/..%2F..%2Fy",
            "/a/..%2Fapi/x/..%2F..%2Fy",
            "/a/%2E%2E/b",
            "/a/..%5Cb",
            "/workspace/./x",
        ):
            status, body = _raw_get(listen, path)
            assert status == 404 and "frontend" not in body, (path, status, body)
        status, body = _raw_get(listen, "//api/artifacts/..%2F..%2Fx")
        assert status == 404 and "artifact_not_found" in body
        # Normal paths still reach their upstream.
        assert _raw_get(listen, "/api/artifacts/abc") == (200, "gateway")
        for path in (
            "/workspace",
            "/workspace/chats/6c0e1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5b",
            "/workspace/artifacts/Qm3x9V2kPz8aLr0tYw4bNc?v=2",
            "/_next/static/chunks/x.js",
            "/_next/static/chunks/app/workspace/page-0a1b2c3d4e5f.js",
            "/mermaid-frame/mermaid.js",
            "/en/docs/getting-started",
            "/workspace/chats?next=%2Fworkspace%2Fhome",
        ):
            assert _raw_get(listen, path) == (200, "frontend"), path
    finally:
        proc.terminate()
        proc.wait(5)
        for server in stubs.values():
            server.shutdown()
