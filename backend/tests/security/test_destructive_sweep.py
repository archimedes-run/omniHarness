"""Every destructive endpoint needs threads:delete, found by enumerating the app.

A list someone maintains by hand misses the next DELETE route; this walks
`app.routes` of the production app instead. The owner signs in, then loses
only `threads:delete`; every DELETE route and every destructive POST must
answer 403. Real HTTP, auth ON.
"""

from __future__ import annotations

import re

import pytest

#: POSTs that destroy or overwrite data, so they count as deletes.
DESTRUCTIVE_POSTS = {
    "/api/workflows/{workflow_id}/archive",
    "/api/memory/cleanup/apply",
    "/api/memory/import",
}

#: DELETE methods that are not a harness deletion, with the reason.
NOT_A_DELETION = {
    # The preview proxy forwards any HTTP verb to the user's own preview app
    # running in the thread's sandbox; it deletes nothing of the harness's and
    # is owner-checked as a thread read.
    "/api/threads/{thread_id}/previews/{preview_id}/proxy",
    "/api/threads/{thread_id}/previews/{preview_id}/proxy/{path:path}",
}


def _destructive_routes(app) -> list[tuple[str, str]]:
    from fastapi.routing import APIRoute

    found = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path in NOT_A_DELETION:
            continue
        query = "&".join(f"{p.alias}=x" for p in route.dependant.query_params if p.field_info.is_required())
        path = re.sub(r"\{[^}]+\}", "x", route.path) + (f"?{query}" if query else "")
        if "DELETE" in route.methods:
            found.append(("DELETE", path))
        if "POST" in route.methods and route.path in DESTRUCTIVE_POSTS:
            found.append(("POST", path))
    return found


def test_the_sweep_finds_the_known_destructive_routes(sec) -> None:
    """Guard on the sweep itself: if enumeration broke, every check below would
    pass vacuously."""
    found = {path.split("?")[0] for _, path in _destructive_routes(sec.app)}
    for expected in ("/api/memory", "/api/agents/x", "/api/threads/x", "/api/workflows/x/archive", "/api/mcp-studio/servers/x"):
        assert expected in found, expected
    assert len(found) >= 15, sorted(found)


def test_every_destructive_route_refuses_without_threads_delete(sec, monkeypatch) -> None:
    from app.gateway import authz

    no_delete = [p for p in authz._ALL_PERMISSIONS if p != "threads:delete"]

    async def perms(user):
        return list(no_delete)

    monkeypatch.setattr("app.gateway.auth_middleware.permissions_for", perms)
    monkeypatch.setattr("app.gateway.authz.permissions_for", perms)
    leaks = []
    for method, path in _destructive_routes(sec.app):
        resp = sec.owner.request(method, path, json={} if method == "POST" else None)
        if resp.status_code != 403:
            leaks.append((method, path, resp.status_code))
    assert not leaks, leaks


@pytest.mark.parametrize("method,path", [("DELETE", "/api/memory/facts/x"), ("POST", "/api/memory/cleanup/apply")])
def test_the_owner_with_threads_delete_gets_past_the_check(sec, method, path) -> None:
    """Positive control: with the permission, the same routes do not answer 403."""
    assert sec.owner.request(method, path, json={} if method == "POST" else None).status_code != 403
