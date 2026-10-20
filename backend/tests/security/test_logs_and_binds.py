"""Logs are never lost, client IPs are real, and nothing binds beyond loopback.

User items B and C of the security baseline.
"""

from __future__ import annotations

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
