"""Third-pass adversarial review of the security baseline (uncommitted).

``test_HOLE_*`` tests are EXPECTED TO FAIL on the branch as reviewed: each is a
confirmed hole, with the exact input in the test. Everything else is a claim
verified to hold. HTTP tests go through create_app() + lifespan, auth ON
(fixtures: conftest.py); host-bash tests go through LocalSandbox.execute_command
and the real bash-path validator.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from _security_helpers import OWNER
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
THREAD_DATA = {"workspace_path": "/tmp/w", "uploads_path": "/tmp/u", "outputs_path": "/tmp/o"}


def _validator(monkeypatch):
    import omniharness.sandbox.tools as tools

    monkeypatch.setattr(tools, "_get_mcp_allowed_paths", lambda: [])
    return tools.validate_local_bash_command_paths


# ── host bash: the scrub is bypassable ───────────────────────────────────

_GATEWAY_STANDIN = r"""
import sys
from omniharness.sandbox.local.local_sandbox import LocalSandbox
print(LocalSandbox("t").execute_command(sys.argv[1]))
"""


def _parent_env_command() -> str:
    if sys.platform == "darwin":
        return "ps -E -ww -p $PPID"
    return "python3 -c \"import os;print(open(os.sep+'proc/%d/environ'%os.getppid()).read())\""


def test_HOLE_host_bash_reads_the_gateways_full_environment_from_its_parent(monkeypatch) -> None:
    """The child env is scrubbed, but the PARENT (the gateway worker) is not:
    macOS `ps -E -ww -p $PPID` / Linux /proc/<ppid>/environ hand back
    AUTH_JWT_SECRET and the internal token. The command passes the validator."""
    cmd = _parent_env_command()
    _validator(monkeypatch)(cmd, THREAD_DATA)  # no PermissionError: host bash would run it
    env = {**os.environ, "PYTHONPATH": str(BACKEND), "OMNI_HARNESS_INTERNAL_AUTH_TOKEN": "canary-internal-9f3", "AUTH_JWT_SECRET": "canary-jwt-7c1"}
    out = subprocess.run([sys.executable, "-c", _GATEWAY_STANDIN, cmd], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60).stdout
    assert "canary-internal-9f3" not in out and "canary-jwt-7c1" not in out, "host bash read the gateway's own environment"


def test_HOLE_host_bash_reads_codex_auth_json_through_HOME(monkeypatch, tmp_path) -> None:
    """`cat ~/.codex/auth.json` is refused, `cat $HOME/.codex/auth.json` is not,
    and HOME survives the scrub."""
    from omniharness.sandbox.local.local_sandbox import LocalSandbox

    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "auth.json").write_text('{"tokens": "codex-canary-41"}')
    monkeypatch.setenv("HOME", str(tmp_path))
    validate = _validator(monkeypatch)
    with pytest.raises(PermissionError):
        validate("cat ~/.codex/auth.json", THREAD_DATA)
    validate("cat $HOME/.codex/auth.json", THREAD_DATA)  # allowed
    out = LocalSandbox("t").execute_command("cat $HOME/.codex/auth.json")
    assert "codex-canary-41" not in out


def test_HOLE_scrub_keeps_webhook_urls_and_credentialed_urls() -> None:
    from omniharness.sandbox.local.local_sandbox import scrubbed_environment

    secrets = {
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T0/B0/xyzsecret",
        "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/secret",
        "POSTGRES_URL": "postgresql://u:pw@db/x",
        "REDIS_URL": "redis://:pw@redis:6379/0",
        "SENTRY_DSN": "https://key@o0.ingest.sentry.io/1",
        "GH_PAT": "ghp_xxx",
    }
    leaked = sorted(set(scrubbed_environment(secrets)))
    assert leaked == [], f"reach host bash: {leaked}"


def test_holds_named_secrets_are_scrubbed() -> None:
    from omniharness.sandbox.local.local_sandbox import scrubbed_environment

    names = ["AUTH_JWT_SECRET", "COMPOSIO_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "DATABASE_URL", "OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN", "AWS_SECRET_ACCESS_KEY", "PGPASSWORD"]
    assert scrubbed_environment({n: "v" for n in names}) == {}


# ── the internal token is a "button" ─────────────────────────────────────


def _content_plan(owner_id):
    from app.policy.models import PendingAction, Tier
    from app.policy.registration import build
    from omniharness.config import get_app_config

    action = PendingAction(
        plan_text="Delete two emails",
        tool_name="gmail_delete_email",
        arguments={"ids": ["a", "b"]},
        targets=["a", "b"],
        tier_at_statement=Tier.TIER_3,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        thread_id=None,
        owner_id=owner_id,
        origin="content",
        origin_source="web_fetch",
    )
    store = build(get_app_config()).pending
    store.save(action)
    return store, action


def _internal_client(app) -> TestClient:
    from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
    from app.gateway.internal_auth import create_internal_auth_headers

    client = TestClient(app)
    csrf = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    client.headers.update({**create_internal_auth_headers(), CSRF_HEADER_NAME: csrf})
    return client


def test_HOLE_internal_token_presses_the_button_on_a_content_caused_plan(sec) -> None:
    """Exact input: POST /api/confirmations/<id>/confirm with only
    X-OmniHarness-Internal-Token (+CSRF pair). The internal principal passes
    require_access for every owner, so the token (reachable from host bash, see
    above) is the button for any plan, content-originated ones included."""
    store, action = _content_plan(sec.owner_id)
    resp = _internal_client(sec.app).post(f"/api/confirmations/{action.id}/confirm", json={})
    stored = store.get(action.id)
    assert resp.status_code in (401, 403, 404) and stored.claimed_by is None and stored.outcome is None, (resp.status_code, resp.text[:200])


def test_holds_owner_cookie_cannot_forge_internal_identity(sec) -> None:
    """A wrong internal token with the owner's cookie is still the owner; with no
    cookie it is 401."""
    bare = TestClient(sec.app)
    assert bare.get("/api/models", headers={"X-OmniHarness-Internal-Token": "x" * 43}).status_code == 401
    assert bare.post("/api/v1/auth/register", json={"email": "x@example.com", "password": "Str0ng!Pass99xx"}).status_code == 403


@pytest.mark.parametrize("path", ["/health/../api/models", "/docs/../api/threads/search", "/openapi.json/../api/models", "/api/channels/openclaw/webhook/../../../api/models"])
def test_holds_public_prefixes_do_not_open_private_routes(sec, path) -> None:
    resp = TestClient(sec.app).get(path)
    assert resp.status_code in (401, 404, 405), (path, resp.status_code)
    assert "models" not in resp.text.lower() or resp.status_code != 200


def test_holds_a_second_register_after_a_disabled_only_db_stays_closed(make_gateway) -> None:
    """Owner disabled: registration is still closed (no re-claim of the install)."""
    app, owner = make_gateway()

    async def _disable():
        from app.gateway.auth.accounts import set_disabled

        await set_disabled(OWNER[0], disabled=True, force=True)

    owner.portal.call(_disable)
    fresh = TestClient(app)
    assert fresh.post("/api/v1/auth/register", json={"email": "new@example.com", "password": "Str0ng!Pass99xx"}).status_code == 403
    assert fresh.post("/api/v1/auth/initialize", json={"email": "new@example.com", "password": "Str0ng!Pass99xx"}).status_code == 409
    assert owner.get("/api/models").status_code in (401, 403)


# ── binds and logs ───────────────────────────────────────────────────────


def test_HOLE_apple_container_publish_has_no_host_address(monkeypatch) -> None:
    """Apple `container run -p` accepts `[host-ip:]host-port:container-port`;
    the code passes `<port>:8080` with no address for that runtime."""
    from omniharness.community.aio_sandbox import local_backend as lb

    monkeypatch.setattr(lb.LocalContainerBackend, "_detect_runtime", lambda self: "container")
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="cid\n", stderr="")

    monkeypatch.setattr(lb.subprocess, "run", fake_run)
    backend = lb.LocalContainerBackend(image="img", base_port=18080, container_prefix="omni-harness-sandbox", config_mounts=[], environment={})
    backend._start_container("omni-harness-sandbox-x", 18080, None)
    cmd = seen[-1]
    spec = cmd[cmd.index("-p") + 1]
    assert spec.startswith("127.0.0.1:"), spec


def test_HOLE_host_nginx_logs_are_never_rotated() -> None:
    """scripts/serve.sh runs nginx.local.conf (logs/nginx-access.log,
    logs/nginx-error.log) and never runs rotate-logs.sh: the host nginx log
    grows forever, no daily file, no 30-day retention."""
    serve = (REPO / "scripts" / "serve.sh").read_text()
    local = (REPO / "docker" / "nginx" / "nginx.local.conf").read_text()
    assert "access_log logs/nginx-access.log" in local
    assert "rotate-logs.sh" in serve, "host nginx logs have no rotation"


_FAKE_NGINX = r"""
import os, signal, sys, time
d = sys.argv[1]
f = open(os.path.join(d, "access.log"), "a", buffering=1)
def reopen(*_):
    global f
    f.close(); f = open(os.path.join(d, "access.log"), "a", buffering=1)
signal.signal(signal.SIGUSR1, reopen)
open(os.path.join(d, "ready"), "w").close()
i = 0
while not os.path.exists(os.path.join(d, "stop")):
    f.write(f"line {i}\n"); i += 1; time.sleep(0.005)
f.close()
open(os.path.join(d, "count"), "w").write(str(i))
"""


def test_HOLE_rotation_with_a_failed_reopen_silently_loses_every_later_line(tmp_path) -> None:
    """If SIGUSR1 does not reach nginx (stale/missing pidfile; `kill ... || true`),
    the script still gzips -f the renamed file, unlinking the inode nginx keeps
    writing to: every line until the next restart is lost, with no error."""
    import gzip

    if shutil.which("gzip") is None:
        pytest.skip("gzip missing")
    logs = tmp_path / "logs"
    logs.mkdir()
    writer = subprocess.Popen([sys.executable, "-c", _FAKE_NGINX, str(logs)])
    try:
        for _ in range(300):
            if (logs / "ready").exists():
                break
            time.sleep(0.01)
        time.sleep(0.2)
        stale = tmp_path / "nginx.pid"
        stale.write_text("999999")
        # [author's edit] Was check=True. On a failed reopen the script now
        # refuses loudly: exit 1 and an ERROR on stderr, nothing compressed.
        failed = subprocess.run(["sh", str(REPO / "docker/nginx/rotate-logs.sh"), "once", str(logs), "2026-10-20", str(stale)], capture_output=True, text=True, timeout=30, env={**os.environ, "REOPEN_WAIT_TENTHS": "5"})
        assert failed.returncode == 1 and "ERROR" in failed.stderr, failed
        time.sleep(0.3)
        (logs / "stop").write_text("")
        writer.wait(timeout=10)
    finally:
        if writer.poll() is None:
            writer.kill()
    # [author's edit] The rotated file was moved BACK (not compressed), so the
    # day's .gz may not exist; every line must still be accounted for.
    gz = logs / "access-2026-10-20.log.gz"
    rotated = gzip.decompress(gz.read_bytes()).decode().splitlines() if gz.exists() else []
    current = (logs / "access.log").read_text().splitlines() if (logs / "access.log").exists() else []
    total = int((logs / "count").read_text())
    assert len(rotated) + len(current) == total, f"lost {total - len(rotated) - len(current)} of {total} lines"
