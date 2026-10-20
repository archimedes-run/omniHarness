"""Logs are never lost, client IPs are real, and nothing binds beyond loopback.

User items B and C of the security baseline.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml
from _security_helpers import OWNER

REPO = Path(__file__).resolve().parents[3]

# ── B1: the gateway log appends, rotates daily, keeps 30 days ─────────────


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)


def _handler(tmp_path, today):
    from app.gateway.log_files import DailyAppendFileHandler

    h = DailyAppendFileHandler(tmp_path / "gateway.log", today=lambda: today[0])
    h.setFormatter(logging.Formatter("%(message)s"))
    return h


def test_the_log_is_appended_across_restarts_never_truncated(tmp_path) -> None:
    today = [date(2026, 10, 20)]
    first = _handler(tmp_path, today)
    first.emit(_record("before the crash"))
    first.close()
    second = _handler(tmp_path, today)  # the restart
    second.emit(_record("after the restart"))
    second.close()
    text = (tmp_path / "gateway.log").read_text()
    assert "before the crash" in text and "after the restart" in text


def test_a_new_day_gets_a_new_file_and_the_symlink_follows(tmp_path) -> None:
    today = [date(2026, 10, 20)]
    h = _handler(tmp_path, today)
    h.emit(_record("day one"))
    today[0] = date(2026, 10, 21)
    h.emit(_record("day two"))
    h.close()
    assert "day one" in (tmp_path / "gateway-2026-10-20.log").read_text()
    assert "day two" in (tmp_path / "gateway-2026-10-21.log").read_text()
    assert (tmp_path / "gateway.log").is_symlink()
    assert (tmp_path / "gateway.log").read_text().strip() == "day two"


def test_thirty_days_are_kept_and_older_files_are_deleted(tmp_path) -> None:
    today = date(2026, 10, 20)
    for age in range(0, 40):
        (tmp_path / f"gateway-{(today - timedelta(days=age)).isoformat()}.log").write_text("x")
    (tmp_path / "unrelated-2000-01-01.log").write_text("keep me")
    h = _handler(tmp_path, [today])
    h.emit(_record("today"))
    h.close()
    kept = sorted(p.name for p in tmp_path.glob("gateway-*.log"))
    assert f"gateway-{(today - timedelta(days=30)).isoformat()}.log" in kept
    assert f"gateway-{(today - timedelta(days=31)).isoformat()}.log" not in kept
    assert len(kept) == 31  # today and the 30 days before it
    assert (tmp_path / "unrelated-2000-01-01.log").exists()


def test_a_plain_log_file_from_the_old_redirect_is_kept(tmp_path) -> None:
    (tmp_path / "gateway.log").write_text("evidence from before rotation\n")
    h = _handler(tmp_path, [date(2026, 10, 20)])
    h.emit(_record("new"))
    h.close()
    preserved = list(tmp_path.glob("gateway-pre-rotation-*.log"))
    assert preserved and "evidence from before rotation" in preserved[0].read_text()


def test_compose_never_truncates_the_gateway_log() -> None:
    for compose in ("docker/docker-compose.yaml", "docker/docker-compose-dev.yaml"):
        text = (REPO / compose).read_text()
        assert not re.search(r"[^>]>\s*/app/logs/", text), f"{compose} truncates a log with '>'"
        assert "GATEWAY_LOG_FILE=/app/logs/gateway.log" in text, compose
    assert not re.search(r"[^>]>\s*\.\./logs/|[^>]>\s*logs/", (REPO / "scripts/serve.sh").read_text())


# ── B2: nginx logs land on the host ───────────────────────────────────────


def test_nginx_logs_go_to_a_host_mount() -> None:
    for compose in ("docker/docker-compose.yaml", "docker/docker-compose-dev.yaml"):
        nginx = yaml.safe_load((REPO / compose).read_text())["services"]["nginx"]
        assert any(str(v).endswith(":/var/log/nginx") for v in nginx.get("volumes", [])), compose
    conf = (REPO / "docker/nginx/nginx.conf").read_text()
    assert "access_log /var/log/nginx/access.log" in conf
    assert "error_log /var/log/nginx/error.log" in conf


# ── B3: the real client IP, trusted only from nginx ──────────────────────


def test_nginx_overwrites_x_forwarded_for_rather_than_appending() -> None:
    for conf in ("docker/nginx/nginx.conf", "docker/nginx/nginx.local.conf"):
        text = (REPO / conf).read_text()
        assert "$proxy_add_x_forwarded_for" not in text, conf
        assert "X-Forwarded-For $remote_addr" in text, conf


def test_the_gateway_trusts_forwarded_headers_only_from_nginxs_fixed_address() -> None:
    for compose, network in (("docker/docker-compose.yaml", "omni-harness"), ("docker/docker-compose-dev.yaml", "omni-harness-dev")):
        doc = yaml.safe_load((REPO / compose).read_text())
        nginx_ip = re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", str(doc["services"]["nginx"]["networks"][network]["ipv4_address"]))
        env = "\n".join(doc["services"]["gateway"]["environment"])
        trusted = re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", re.search(r"GATEWAY_TRUSTED_PROXIES=(\S+)", env).group(1))
        assert trusted == nginx_ip, (compose, trusted, nginx_ip)


def _lock_out(client, *, xff: str) -> None:
    for _ in range(5):
        client.post("/api/v1/auth/login/local", data={"username": OWNER[0], "password": "Wr0ng!Password"}, headers={"X-Forwarded-For": xff})


def _login_status(client, *, xff: str) -> int:
    return client.post("/api/v1/auth/login/local", data={"username": OWNER[0], "password": OWNER[1]}, headers={"X-Forwarded-For": xff}).status_code


def test_a_spoofed_x_forwarded_for_from_a_non_proxy_peer_is_ignored(make_gateway, monkeypatch) -> None:
    """The peer (TestClient's "testclient") is not the trusted proxy, so a
    rotating X-Forwarded-For does not escape the per-IP login lockout."""
    monkeypatch.setenv("GATEWAY_TRUSTED_PROXIES", "10.9.9.10")
    from fastapi.testclient import TestClient

    app, _ = make_gateway()
    client = TestClient(app)
    _lock_out(client, xff="1.1.1.1")
    assert _login_status(client, xff="2.2.2.2") == 429  # same peer, still locked


def test_x_forwarded_for_from_the_trusted_proxy_is_the_client(make_gateway, monkeypatch) -> None:
    """Positive control: from the trusted peer, each forwarded client is its own."""
    monkeypatch.setenv("GATEWAY_TRUSTED_PROXIES", "testclient")
    from fastapi.testclient import TestClient

    app, _ = make_gateway()
    client = TestClient(app)
    _lock_out(client, xff="1.1.1.1")
    assert _login_status(client, xff="1.1.1.1") == 429
    assert _login_status(client, xff="2.2.2.2") == 200


# ── C: nothing binds beyond loopback ──────────────────────────────────────

_LOOPBACK = ("127.0.0.1:", "[::1]:")


class _ComposeLoader(yaml.SafeLoader):
    """Compose's merge tags (!override, !reset) parsed as their plain value."""


_ComposeLoader.add_multi_constructor(
    "!", lambda loader, suffix, node: loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node) if isinstance(node, yaml.MappingNode) else loader.construct_scalar(node)
)


def _resolve_defaults(spec: str) -> str:
    return re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", spec)


@pytest.mark.parametrize("compose", sorted(p.relative_to(REPO).as_posix() for p in (REPO / "docker").glob("*.y*ml")))
def test_every_compose_port_is_published_on_loopback(compose) -> None:
    doc = yaml.load((REPO / compose).read_text(), Loader=_ComposeLoader) or {}  # noqa: S506 - a SafeLoader subclass
    exposed = []
    for name, svc in (doc.get("services") or {}).items():
        for port in (svc or {}).get("ports") or []:
            spec = _resolve_defaults(str(port["published"] if isinstance(port, dict) else port))
            host_ip = port.get("host_ip", "") if isinstance(port, dict) else None
            if isinstance(port, dict):
                ok = host_ip in ("127.0.0.1", "::1")
            else:
                ok = spec.startswith(_LOOPBACK)
            if not ok:
                exposed.append((name, str(port)))
    assert not exposed, f"{compose} publishes beyond loopback: {exposed}"


def test_local_runs_bind_loopback() -> None:
    serve = (REPO / "scripts/serve.sh").read_text()
    makefile = (REPO / "backend/Makefile").read_text()
    nginx_local = (REPO / "docker/nginx/nginx.local.conf").read_text()
    assert "--host 0.0.0.0" not in serve and "--host 127.0.0.1" in serve
    assert "--host 0.0.0.0" not in makefile and makefile.count("--host 127.0.0.1") >= 2
    assert re.search(r"next dev[^\n\"]*-H 127\.0\.0\.1", serve) and re.search(r"next start -H 127\.0\.0\.1", serve)
    for listen in re.findall(r"^\s*listen\s+([^;]+);", nginx_local, flags=re.M):
        assert listen.strip().startswith(("127.0.0.1:", "[::1]:")), listen


def test_live_omni_containers_publish_only_on_loopback() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker CLI not installed: live container ports NOT checked")
    try:
        out = subprocess.run([docker, "ps", "--filter", "name=omni", "--format", "{{.Names}}\t{{.Ports}}"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"docker not reachable ({exc}): live container ports NOT checked")
    if out.returncode != 0:
        pytest.skip(f"docker not reachable ({out.stderr.strip()[:120]}): live container ports NOT checked")
    exposed = []
    for line in out.stdout.splitlines():
        name, _, ports = line.partition("\t")
        for mapping in filter(None, (p.strip() for p in ports.split(","))):
            if "->" in mapping and not mapping.startswith(("127.0.0.1:", "[::1]:")):
                exposed.append((name, mapping))
    assert not exposed, f"live containers published beyond loopback: {exposed}"


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["/venv/bin/uvicorn", "app.gateway.app:app", "--host", "0.0.0.0", "--port", "8001"], ("0.0.0.0", 8001)),
        (["/venv/bin/uvicorn", "app.gateway.app:app", "--host=127.0.0.1", "--port=9"], ("127.0.0.1", 9)),
        (["/venv/bin/uvicorn", "app.gateway.app:app"], ("127.0.0.1", 8000)),
        (["/venv/bin/pytest", "tests"], None),
    ],
)
def test_the_logged_bind_is_the_real_one(argv, expected) -> None:
    from app.gateway.config import actual_bind, get_gateway_config

    assert actual_bind(argv) == expected
    assert get_gateway_config().host != "0.0.0.0" or __import__("os").environ.get("GATEWAY_HOST") == "0.0.0.0"


def test_a_child_loggers_preview_token_is_redacted_in_the_file(tmp_path, monkeypatch) -> None:
    """Logger filters do not see records a child logger propagates; the file
    handler's own filter does. Other root handlers are set aside first: a
    filter on one of them mutates the record and would hide the difference."""
    from app.gateway.log_files import install_log_file

    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    handler = install_log_file(str(tmp_path / "gateway.log"))
    try:
        logging.getLogger("some.child.module").warning("GET /api/threads/t/artifacts/preview-token/SECRETTOKEN123/x")
    finally:
        for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
            logging.getLogger(name).removeHandler(handler)
        handler.close()
    text = (tmp_path / "gateway.log").read_text()
    assert "SECRETTOKEN123" not in text and "[redacted]" in text


def test_four_workers_starting_at_once_keep_the_old_log(tmp_path) -> None:
    import threading

    (tmp_path / "gateway.log").write_text("line from before rotation\n")
    today = [date(2026, 10, 20)]
    handlers = [_handler(tmp_path, today) for _ in range(4)]
    barrier = threading.Barrier(4)

    def start(h, i):
        barrier.wait()
        h.emit(_record(f"worker {i}"))

    threads = [threading.Thread(target=start, args=(h, i)) for i, h in enumerate(handlers)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    [h.close() for h in handlers]
    kept = "".join(p.read_text() for p in tmp_path.glob("gateway-pre-rotation-*.log"))
    assert "line from before rotation" in kept
    assert (tmp_path / "gateway.log").is_symlink()
    today_lines = (tmp_path / "gateway-2026-10-20.log").read_text().splitlines()
    assert sorted(today_lines) == [f"worker {i}" for i in range(4)]


def test_host_bash_never_sees_the_internal_token_or_api_keys(monkeypatch) -> None:
    from omniharness.sandbox.local.local_sandbox import scrubbed_environment

    secrets = {k: "x" for k in ("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "AUTH_JWT_SECRET", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "GITHUB_TOKEN", "MY_SERVICE_PASSWORD", "FERNET_KEY")}
    env = scrubbed_environment({"PATH": "/usr/bin", "HOME": "/h", **secrets})
    assert env == {"PATH": "/usr/bin", "HOME": "/h"}


# ── nginx log rotation (docker/nginx/rotate-logs.sh) ──────────────────────

_FAKE_NGINX = r"""
import os, signal, sys, time
d = sys.argv[1]
f = open(os.path.join(d, "access.log"), "a", buffering=1)
def reopen(*_):
    global f
    f.close()
    f = open(os.path.join(d, "access.log"), "a", buffering=1)
    open(os.path.join(d, "error.log"), "a").close()  # nginx reopens every log
signal.signal(signal.SIGUSR1, reopen)
open(os.path.join(d, "ready"), "w").close()
i = 0
while not os.path.exists(os.path.join(d, "stop")):
    f.write(f"line {i}\n"); i += 1
    time.sleep(0.005)
f.write(f"line {i}\n")
f.close()
open(os.path.join(d, "count"), "w").write(str(i + 1))
"""


def test_nginx_rotation_loses_no_lines_compresses_and_keeps_30_days(tmp_path) -> None:
    import gzip
    import os
    import sys
    import time

    if shutil.which("gzip") is None:
        pytest.skip("gzip not installed: nginx rotation NOT checked")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "error.log").write_text("an error\n")
    old = logs / "access-2026-08-01.log.gz"
    old.write_bytes(gzip.compress(b"old\n"))
    recent = logs / "access-2026-10-01.log.gz"
    recent.write_bytes(gzip.compress(b"recent\n"))
    now = time.time()
    os.utime(old, (now - 40 * 86400, now - 40 * 86400))
    os.utime(recent, (now - 19 * 86400, now - 19 * 86400))

    writer = subprocess.Popen([sys.executable, "-c", _FAKE_NGINX, str(logs)])
    try:
        for _ in range(200):
            if (logs / "ready").exists():
                break
            time.sleep(0.01)
        time.sleep(0.2)
        pidfile = tmp_path / "nginx.pid"
        pidfile.write_text(str(writer.pid))
        result = subprocess.run(["sh", str(REPO / "docker/nginx/rotate-logs.sh"), "once", str(logs), "2026-10-20", str(pidfile)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        time.sleep(0.2)
        (logs / "stop").write_text("")
        writer.wait(timeout=10)
    finally:
        writer.kill() if writer.poll() is None else None
    rotated = gzip.decompress((logs / "access-2026-10-20.log.gz").read_bytes()).decode().splitlines()
    current = (logs / "access.log").read_text().splitlines()
    total = int((logs / "count").read_text())
    assert rotated and current, "both the rotated day and the reopened file have lines"
    assert sorted(rotated + current, key=lambda line: int(line.split()[1])) == [f"line {i}" for i in range(total)], "a line was lost or duplicated"
    assert gzip.decompress((logs / "error-2026-10-20.log.gz").read_bytes()) == b"an error\n"
    assert not old.exists(), "older than 30 days must go"
    assert recent.exists(), "within 30 days must stay"
    assert not (logs / "access-2026-10-20.log").exists(), "the rotated day is compressed"


def test_both_compose_files_run_the_nginx_rotation() -> None:
    for compose in ("docker/docker-compose.yaml", "docker/docker-compose-dev.yaml"):
        text = (REPO / compose).read_text()
        assert "rotate-logs.sh loop /var/log/nginx /tmp/nginx.pid &" in text, compose
        assert "./nginx/rotate-logs.sh:/etc/nginx/rotate-logs.sh:ro" in text, compose
    assert "pid /tmp/nginx.pid;" in (REPO / "docker/nginx/nginx.conf").read_text()


def test_nginx_sets_forwarded_headers_itself_in_every_proxied_location() -> None:
    for conf in ("docker/nginx/nginx.conf", "docker/nginx/nginx.local.conf"):
        text = (REPO / conf).read_text()
        for block in re.split(r"\n\s*location ", text)[1:]:
            if "proxy_pass" not in block:
                continue
            head = block.split("\n", 1)[0]
            assert 'proxy_set_header Forwarded "";' in block, (conf, head)
            assert "proxy_set_header X-Forwarded-Host $http_host;" in block, (conf, head)
            assert 'proxy_set_header X-Forwarded-Port "";' in block, (conf, head)


# ── every dev/test/run config in the repo binds loopback ─────────────────

#: 0.0.0.0 that stays, each with its reason, AND the published side that makes
#: it safe: every compose service running that image or command, each of which
#: must publish nothing or only on loopback
#: (test_each_container_exception_is_unpublished_or_loopback).
_C, _D, _Y = "docker/docker-compose.yaml", "docker/docker-compose-dev.yaml", "docker/docker-compose-daily.yaml"
CONTAINER_INTERNAL = {
    "backend/Dockerfile": ("gateway (and session-watcher) inside their containers", [(_C, "gateway"), (_D, "gateway"), (_C, "session-watcher"), (_D, "session-watcher")]),
    _C: ("the gateway command inside its container; nginx reaches gateway:8001", [(_C, "gateway")]),
    _D: ("the gateway command inside its container; nginx reaches gateway:8001", [(_D, "gateway")]),
    "docker/provisioner/Dockerfile": ("the provisioner inside its container; nginx reaches provisioner:8002", [(_C, "provisioner"), (_D, "provisioner")]),
    "frontend/Dockerfile": ("NEXT_HOST=0.0.0.0 inside the frontend container; nginx reaches frontend:3000", [(_C, "frontend"), (_D, "frontend"), (_Y, "frontend")]),
}


def _compose(rel: str) -> dict:
    return yaml.load((REPO / rel).read_text(), Loader=_ComposeLoader) or {}  # noqa: S506 - a SafeLoader subclass


def _built_from(rel_dockerfile: str) -> set[tuple[str, str]]:
    """Every (compose file, service) whose build uses this Dockerfile."""
    found = set()
    for compose in (_C, _D, _Y):
        for name, svc in (_compose(compose).get("services") or {}).items():
            build = (svc or {}).get("build")
            if isinstance(build, dict) and build.get("dockerfile"):
                path = ((REPO / "docker" / build.get("context", ".")) / build["dockerfile"]).resolve()
                if path == (REPO / rel_dockerfile).resolve():
                    found.add((compose, name))
    return found


@pytest.mark.parametrize("exception", sorted(CONTAINER_INTERNAL))
def test_each_container_exception_is_unpublished_or_loopback(exception) -> None:
    """The 0.0.0.0 inside the container is safe ONLY because its host side
    publishes nothing, or only on loopback. Checked per exception."""
    _, services = CONTAINER_INTERNAL[exception]
    if exception.endswith("Dockerfile"):
        missing = _built_from(exception) - set(services)
        assert not missing, f"{exception} is also built into {missing}: list them so their published side is checked"
    assert services
    for compose, name in services:
        svc = (_compose(compose).get("services") or {}).get(name)
        assert svc is not None, (compose, name)
        for port in svc.get("ports") or []:
            if isinstance(port, dict):
                assert port.get("host_ip") in ("127.0.0.1", "::1"), (compose, name, port)
            else:
                assert _resolve_defaults(str(port)).startswith(_LOOPBACK), (compose, name, port)


def _repo_files(*patterns: str) -> list[Path]:
    out = subprocess.run(["git", "ls-files", *patterns], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    return [REPO / p for p in out]


def test_playwright_web_servers_bind_loopback() -> None:
    configs = _repo_files("*playwright*.config.ts")
    assert configs, "the sweep found no Playwright config"
    for path in configs:
        text = path.read_text()
        assert "0.0.0.0" not in text, path
        for command in re.findall(r"command:\s*[\"'`]([^\"'`]+)", text):
            assert re.search(r"(-H|--hostname)\s+127\.0\.0\.1", command), (path.name, command)
        for url in re.findall(r"(?:baseURL|url):\s*[\"'`](https?://[^\"'`]+)", text):
            assert re.match(r"https?://(127\.0\.0\.1|localhost)(:|/|$)", url), (path.name, url)


def test_next_scripts_bind_loopback_by_default() -> None:
    for path in _repo_files("*package.json"):
        if "node_modules" in path.parts:
            continue
        scripts = json.loads(path.read_text()).get("scripts", {})
        for name, script in scripts.items():
            for command in re.findall(r"next (?:dev|start)[^&;|]*", script):
                assert re.search(r"(-H|--hostname)\s+(127\.0\.0\.1|\$\{NEXT_HOST:-127\.0\.0\.1\})", command), (path, name, command)


def test_uvicorn_on_the_host_binds_loopback() -> None:
    files = _repo_files("Makefile", "*/Makefile", "scripts/*", "*Dockerfile", "docker/*.y*ml")
    for path in files:
        rel = path.relative_to(REPO).as_posix()
        for host in re.findall(r"uvicorn[^\n\"]*?--host[ =](\S+)", path.read_text()):
            if host == "0.0.0.0":
                assert rel in CONTAINER_INTERNAL, f"{rel}: uvicorn --host 0.0.0.0 on the host"
                # ...and only because its published side is checked:
                test_each_container_exception_is_unpublished_or_loopback(rel)
            else:
                assert host == "127.0.0.1", (rel, host)


def test_docker_run_port_publishes_are_loopback() -> None:
    """Every `-p` the code builds for `docker run` / Apple `container run`
    names 127.0.0.1 (or the loopback-defaulting resolver). No exceptions."""
    found = 0
    for path in _repo_files("*.py", "*.sh"):
        rel = path.relative_to(REPO).as_posix()
        if "/tests/" in f"/{rel}" or rel.startswith("skills/"):
            continue
        text = path.read_text(errors="ignore")
        for mapping in re.findall(r'"-p",\s*(?:#[^\n]*\n\s*)*(f?"[^"]+")', text) + re.findall(r'port_mapping = (f"[^"]+")', text):
            found += 1
            assert mapping.startswith(('f"127.0.0.1:', '"127.0.0.1:', 'f"{_resolve_docker_bind_host()}:')), (rel, mapping)
        for mapping in re.findall(r"docker run[^\n]*\s-p\s+(\S+)", text):
            found += 1
            assert mapping.startswith("127.0.0.1:"), (rel, mapping)
    assert found >= 2, "the sweep found no docker -p at all"
    from omniharness.community.aio_sandbox.local_backend import _resolve_docker_bind_host

    assert _resolve_docker_bind_host(sandbox_host="host.docker.internal", bind_host=None) == "127.0.0.1"


def test_no_host_command_execution_remains(monkeypatch):
    """The host-bash path is gone: LocalSandbox runs nothing."""
    from omniharness.sandbox.local.local_sandbox import HOST_EXECUTION_REMOVED, LocalSandbox

    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "internal-token-value-xyz")
    out = LocalSandbox("t").execute_command("env")
    assert out == HOST_EXECUTION_REMOVED and "internal-token-value-xyz" not in out


def test_console_captures_are_capped_without_losing_the_capture(tmp_path) -> None:
    import gzip

    if shutil.which("gzip") is None:
        pytest.skip("gzip not installed: cap NOT checked")
    log = tmp_path / "gateway.console.log"
    log.write_text("x" * 2000 + "\n")
    subprocess.run(["sh", str(REPO / "docker/nginx/rotate-logs.sh"), "cap", str(log), "1000"], check=True, timeout=30)
    [kept] = list(tmp_path.glob("gateway.console-*.log.gz"))
    assert gzip.decompress(kept.read_bytes()).decode() == "x" * 2000 + "\n"
    assert log.read_text() == ""
    subprocess.run(["sh", str(REPO / "docker/nginx/rotate-logs.sh"), "cap", str(log), "1000"], check=True, timeout=30)
    assert len(list(tmp_path.glob("gateway.console-*.log.gz"))) == 1  # under the cap: untouched


def test_the_host_nginx_and_console_logs_are_rotated_by_serve_sh() -> None:
    serve = (REPO / "scripts/serve.sh").read_text()
    assert 'LOG_NAMES="nginx-access nginx-error"' in serve and "rotate-logs.sh loop logs logs/nginx.pid" in serve
    caps = re.search(r'CAP_FILES="([^"]+)"', serve).group(1).split()
    assert {"logs/gateway.console.log", "logs/frontend.log", "logs/nginx.log"} <= set(caps)
    local = (REPO / "docker/nginx/nginx.local.conf").read_text()
    assert "pid logs/nginx.pid;" in local


def test_old_pre_rotation_copies_follow_retention(tmp_path) -> None:
    import os
    import time

    old = tmp_path / "gateway-pre-rotation-1.log"
    old.write_text("old")
    os.utime(old, (time.time() - 40 * 86400, time.time() - 40 * 86400))
    recent = tmp_path / "gateway-pre-rotation-2.log"
    recent.write_text("recent")
    h = _handler(tmp_path, [date(2026, 10, 20)])
    h.emit(_record("x"))
    h.close()
    assert not old.exists() and recent.exists()
