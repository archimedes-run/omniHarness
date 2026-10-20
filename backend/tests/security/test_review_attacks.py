"""Independent adversarial review of the security baseline (item 0 a-d).

Every test asserts the SAFE behaviour; a failing test is a confirmed hole.
Real HTTP against create_app() + lifespan, auth ON (fixtures in conftest.py).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from pathlib import Path

import pytest
from _security_helpers import OWNER, SECOND
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[3]


def _minted(sec, user_id: str) -> TestClient:
    from app.gateway.auth import create_access_token

    client = TestClient(sec.app)
    client.cookies.set("access_token", create_access_token(user_id, token_version=0))
    client.cookies.set("csrf_token", "csrf-pair")
    client.headers["X-CSRF-Token"] = "csrf-pair"
    return client


async def _count_users() -> int:
    from sqlalchemy import func, select

    from omniharness.persistence.engine import get_session_factory
    from omniharness.persistence.user.model import UserRow

    async with get_session_factory()() as s:
        return (await s.execute(select(func.count()).select_from(UserRow))).scalar_one()


# ── (a) registration closure ─────────────────────────────────────────────


def test_atk_register_race_creates_at_most_one_account(make_gateway) -> None:
    """Fire concurrent first registrations (and /initialize) on a fresh install."""
    app, client = make_gateway(initialize=False)
    results: list[int] = []
    barrier = threading.Barrier(8)

    def go(i: int) -> None:
        c = TestClient(app)
        barrier.wait()
        path = "/api/v1/auth/register" if i % 2 else "/api/v1/auth/initialize"
        results.append(c.post(path, json={"email": f"racer{i}@example.com", "password": "Str0ng!Pass99x"}).status_code)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    n = client.portal.call(_count_users)
    assert n == 1, f"{n} accounts created by a concurrent first registration; statuses={sorted(results)}"


@pytest.mark.parametrize("email", [" OWNER@example.com", "Owner@Example.com", "owner@example.com ", "new@example.com"])
def test_atk_register_variants_after_owner_are_closed(sec, email) -> None:
    resp = TestClient(sec.app).post("/api/v1/auth/register", json={"email": email, "password": "Str0ng!Pass99x"})
    assert resp.status_code in (403, 422), resp.text
    assert sec.owner.portal.call(_count_users) == 2  # owner + fixture's second


def test_atk_initialize_creates_no_account_once_one_exists(make_gateway) -> None:
    """A non-admin account exists (legacy install). /initialize counts ADMINS,
    not accounts, so it is still a user-creating door."""
    app, client = make_gateway(initialize=False)

    async def _mk():
        from app.gateway.deps import get_local_provider

        await get_local_provider().create_user(email=OWNER[0], password=OWNER[1], system_role="user")

    client.portal.call(_mk)
    resp = TestClient(app).post("/api/v1/auth/initialize", json={"email": "late@example.com", "password": "Str0ng!Pass99x"})
    assert client.portal.call(_count_users) == 1, f"/initialize created an account after one existed ({resp.status_code})"


def test_atk_login_is_not_a_password_oracle_for_refused_accounts(sec) -> None:
    right = TestClient(sec.app).post("/api/v1/auth/login/local", data={"username": SECOND[0], "password": SECOND[1]})
    wrong = TestClient(sec.app).post("/api/v1/auth/login/local", data={"username": SECOND[0], "password": "Wrong!Pass000"})
    assert right.status_code == wrong.status_code, f"right password -> {right.status_code}, wrong -> {wrong.status_code}"


# ── (a) the owner-only door, every route ─────────────────────────────────


_PUBLIC = {"/api/channels/openclaw/webhook", "/api/v1/auth/login/local", "/api/v1/auth/register", "/api/v1/auth/logout", "/api/v1/auth/setup-status", "/api/v1/auth/initialize"}


def test_atk_every_route_refuses_the_second_accounts_session(sec) -> None:
    from fastapi.routing import APIRoute

    other = _minted(sec, sec.second_id)
    leaks = []
    for route in sec.app.routes:
        if not isinstance(route, APIRoute) or route.path in _PUBLIC or route.path.startswith(("/docs", "/redoc", "/openapi", "/health")):
            continue
        path = re.sub(r"\{[^}]+\}", "x", route.path)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if "preview-token" in route.path:
                continue
            resp = other.request(method, path, json={} if method in ("POST", "PUT", "PATCH") else None)
            if resp.status_code != 403:
                leaks.append((method, route.path, resp.status_code))
    assert not leaks, leaks


def test_atk_old_owner_session_dies_when_the_owner_changes(sec, monkeypatch) -> None:
    monkeypatch.setenv("OMNI_HARNESS_OWNER_USER_ID", sec.second_id)
    assert sec.owner.get("/api/v1/auth/me").status_code == 403


# ── (b) server-owned context ─────────────────────────────────────────────


@pytest.fixture
def captured(monkeypatch):
    seen: list[dict] = []

    def factory(config, **_):
        seen.append({"configurable": dict(config.get("configurable") or {}), "context": dict(config.get("context") or {}), "metadata": dict(config.get("metadata") or {})})
        raise RuntimeError("captured")

    monkeypatch.setattr("app.gateway.services.resolve_agent_factory", lambda assistant_id: factory)
    return seen


def _run(client, tid: str, body: dict):
    resp = client.post(f"/api/threads/{tid}/runs/wait", json=body)
    assert resp.status_code in (200, 500), resp.text
    return resp


def test_atk_delegation_identity_keys_cannot_be_smuggled_via_config_context(sec, captured) -> None:
    """invited_agent / delegation_chain are what the policy middleware reads as
    WHO is asking (requester, plan text, inviting-turn origin); sandbox_id is
    what SandboxMiddleware releases. They are set by delegation, like called_agent."""
    owner = sec.owner
    tid = owner.post("/api/threads", json={}).json()["thread_id"]
    body = {
        "assistant_id": "lead_agent",
        "input": {"messages": [{"role": "human", "content": "hi"}]},
        "config": {"context": {"invited_agent": "trusted-agent", "delegation_chain": ["lead_agent", "trusted-agent"], "sandbox_id": "other-threads-sandbox"}},
    }
    _run(owner, tid, body)
    [cfg] = captured
    smuggled = {k: cfg["context"][k] for k in ("invited_agent", "delegation_chain", "sandbox_id") if k in cfg["context"]}
    assert not smuggled, f"reached runtime.context: {smuggled}"


def test_atk_trigger_credential_is_derivable_by_any_internal_token_holder(sec, captured) -> None:
    """The 'trigger engine credential' is HMAC(internal_token, a constant in
    the source). A channel (or anything) holding the internal token computes it
    without help from the trigger engine, and it is a static, replayable header."""
    from app.gateway import internal_auth

    token = internal_auth._INTERNAL_AUTH_TOKEN  # what every channel already holds
    derived = hmac.new(token.encode(), b"omniharness/trigger-engine/v1", hashlib.sha256).hexdigest()
    client = TestClient(sec.app)
    client.cookies.set("csrf_token", "c")
    client.headers.update({"X-OmniHarness-Internal-Token": token, "X-OmniHarness-Trigger-Engine": derived, "X-CSRF-Token": "c"})
    tid = client.post("/api/threads", json={}).json()["thread_id"]
    body = {"assistant_id": "lead_agent", "input": {"messages": [{"role": "human", "content": "x"}]}, "config": {"configurable": {"turn_provenance": "synthetic-trigger", "trigger_rule_id": "r"}}}
    _run(client, tid, body)
    [cfg] = captured
    assert cfg["context"].get("turn_provenance") != "synthetic-trigger", "a holder of the internal token minted a scheduled run"


def test_atk_agent_traversal_via_assistant_id_is_refused(sec, captured) -> None:
    tid = sec.owner.post("/api/threads", json={}).json()["thread_id"]
    for bad in ("../other", "..%2fother", "a/b", "users/x/agents/y"):
        body = {"assistant_id": bad, "input": {"messages": []}}
        assert sec.owner.post(f"/api/threads/{tid}/runs/wait", json=body).status_code == 422, bad
    assert captured == []


# ── (c) ownership, door opened ───────────────────────────────────────────


@pytest.fixture
def two(sec):
    sec.admit_second()
    return sec, sec.login_second()


def test_atk_policy_audit_is_per_owner(two, tmp_path) -> None:
    sec, other = two
    audit = tmp_path / "policy" / "audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": "2026-10-20T10:00:00",
        "actor": sec.owner_id,
        "tier": 3,
        "tool": "gmail_send",
        "plan_as_stated": "Send the owner's private mail to the bank",
        "targets": ["bank@example.com"],
        "authorised_by": sec.owner_id,
        "outcome": "confirmed",
        "action_id": "a1",
        "thread_id": "t1",
    }  # noqa: E501
    audit.write_text(json.dumps(entry) + "\n")
    assert sec.owner.get("/api/policy/audit").json(), "positive control: the owner sees it"
    seen = other.get("/api/policy/audit").json()
    assert not seen, f"second account read the owner's Tier 3 audit: {seen}"


def test_atk_mcp_studio_list_is_per_owner(two, monkeypatch) -> None:
    sec, other = two
    monkeypatch.setattr("app.gateway.routers.mcp_studio._check_flag", lambda request: None)

    async def _mk():
        from app.gateway.deps import get_mcp_server_repo

        repo = get_mcp_server_repo(type("R", (), {"app": sec.app})())
        return await repo.create(name="owners-bank-scraper", owner_id=sec.owner_id, description="private")

    try:
        sec.owner.portal.call(_mk)
    except Exception as exc:  # repo unavailable in this config
        pytest.skip(f"no mcp repo: {exc}")
    assert "owners-bank-scraper" in [s["name"] for s in sec.owner.get("/api/mcp-studio/servers").json()["servers"]], "positive control"
    names = [s["name"] for s in other.get("/api/mcp-studio/servers").json()["servers"]]
    assert "owners-bank-scraper" not in names, names


def test_atk_untracked_thread_is_not_readable_by_another_account(two, captured) -> None:
    """A thread id with no threads_meta row passes every read check."""
    sec, other = two
    resp = sec.owner.post("/api/runs/wait", json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "human", "content": "secret"}]}})
    assert resp.status_code in (200, 500)
    tid = (resp.headers.get("content-location") or "").split("/")[3] if resp.headers.get("content-location") else None
    runs = sec.owner.post("/api/threads/search", json={}).json()
    tids = [t["thread_id"] for t in runs]
    if tid is None and tids:
        tid = tids[0]
    assert tid, "could not find the auto-created thread"
    assert other.get(f"/api/threads/{tid}/runs").status_code == 404
    assert other.get(f"/api/threads/{tid}").status_code == 404


def test_atk_existence_oracle_404_same_for_owned_and_missing(two) -> None:
    sec, other = two
    tid = sec.owner.post("/api/threads", json={}).json()["thread_id"]
    owned = other.get(f"/api/threads/{tid}/state")
    missing = other.get("/api/threads/00000000-0000-0000-0000-000000000000/state")
    assert owned.status_code == missing.status_code, (owned.status_code, owned.text, missing.status_code, missing.text)


_DESTRUCTIVE = [
    ("DELETE", "/api/agents/some-agent"),
    ("DELETE", "/api/memory"),
    ("DELETE", "/api/memory/facts/f1"),
    ("DELETE", "/api/skills/custom/some-skill"),
    ("DELETE", "/api/mcp-studio/servers/s1"),
    ("DELETE", "/api/automations/rules/r1?version=v"),
    ("DELETE", "/api/ledger/links/l1"),
    ("DELETE", "/api/composio/connections/GMAIL"),
    ("POST", "/api/workflows/w1/archive"),
    ("POST", "/api/memory/cleanup/apply"),
]


@pytest.mark.parametrize("method,path", _DESTRUCTIVE)
def test_atk_destructive_routes_need_threads_delete(sec, monkeypatch, method, path) -> None:
    from app.gateway import authz

    no_delete = [p for p in authz._ALL_PERMISSIONS if p != "threads:delete"]
    assert len(no_delete) == len(authz._ALL_PERMISSIONS) - 1

    async def perms(user):
        return list(no_delete)

    monkeypatch.setattr("app.gateway.auth_middleware.permissions_for", perms)
    monkeypatch.setattr("app.gateway.authz.permissions_for", perms)
    resp = sec.owner.request(method, path, json={} if method == "POST" else None)
    assert resp.status_code == 403, f"{method} {path} -> {resp.status_code} without threads:delete"


# ── (d) binding ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("compose", ["docker/docker-compose-dev.yaml", "docker/docker-compose.yaml"])
def test_atk_compose_publishes_only_on_loopback(compose) -> None:
    import yaml

    doc = yaml.safe_load((REPO / compose).read_text())
    exposed = []
    for name, svc in (doc.get("services") or {}).items():
        for port in svc.get("ports") or []:
            # [author's edit] Resolve ${VAR:-default} to its default, as compose
            # does with the variable unset: #60 publishes "${BIND_ADDR:-127.0.0.1}:..."
            # (loopback unless the operator opts out), which a literal prefix check
            # misreads as all interfaces.
            spec = re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", str(port))
            if not spec.startswith(("127.0.0.1:", "[::1]:", "localhost:")):
                exposed.append((name, spec))
    assert not exposed, f"published on every host interface: {exposed}"
