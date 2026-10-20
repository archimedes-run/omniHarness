"""/api/ledger: the user's direct edits (FR-007, FR-011 to FR-014).

Through the app as startup builds it (conftest), so the routes, the service
and the database are the production ones.
"""

from __future__ import annotations


def _project(gateway, name="Beta launch") -> dict:
    resp = gateway.client.post("/api/ledger/projects", json={"name": name, "why": "Ship it"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_read_and_edit_a_project_with_goals_tasks_and_notes(gateway) -> None:
    c = gateway.client
    p = _project(gateway)
    goal = c.post(f"/api/ledger/projects/{p['id']}/goals", json={"title": "Live", "definition_of_done": "Anyone can sign up", "target_date": "2026-12-01"}).json()
    t1 = c.post(f"/api/ledger/projects/{p['id']}/tasks", json={"title": "Landing page", "due_date": "2026-11-01", "owner": "me", "goal_id": goal["id"]}).json()
    t2 = c.post(f"/api/ledger/projects/{p['id']}/tasks", json={"title": "Waitlist", "goal_id": goal["id"]}).json()
    assert (t1["short_id"], t2["short_id"]) == ("T-1", "T-2")
    assert t1["owner"] == {"kind": "user", "ref": None}
    c.post(f"/api/ledger/projects/{p['id']}/notes", json={"decided": "Use Resend", "why": "simple API"})

    done = c.patch(f"/api/ledger/tasks/{t1['id']}", json={"version": t1["version"], "status": "done"}).json()
    assert done["status"] == "done" and done["done_at"]

    view = c.get(f"/api/ledger/projects/{p['id']}").json()
    assert view["goals"][0]["progress"] == {"done": 1, "total": 2}
    assert [n["decided"] for n in view["notes"]] == ["Use Resend"]
    [summary] = c.get("/api/ledger/projects").json()
    assert (summary["open_tasks"], summary["done_tasks"]) == (1, 1)


def test_a_stale_edit_is_refused_with_the_current_row(gateway) -> None:
    c = gateway.client
    p = _project(gateway)
    t = c.post(f"/api/ledger/projects/{p['id']}/tasks", json={"title": "A"}).json()
    assert c.patch(f"/api/ledger/tasks/{t['id']}", json={"version": t["version"], "title": "B"}).status_code == 200
    stale = c.patch(f"/api/ledger/tasks/{t['id']}", json={"version": t["version"], "title": "C"})
    assert stale.status_code == 409
    assert stale.json()["detail"]["current"]["title"] == "B"


def test_clearing_a_due_date_is_explicit(gateway) -> None:
    c = gateway.client
    p = _project(gateway)
    t = c.post(f"/api/ledger/projects/{p['id']}/tasks", json={"title": "A", "due_date": "2026-11-01"}).json()
    cleared = c.patch(f"/api/ledger/tasks/{t['id']}", json={"version": t["version"], "clear": ["due_date"]}).json()
    assert cleared["due_date"] is None


def test_promoting_a_threads_todos_creates_linked_tasks_and_attaches_the_thread(gateway) -> None:
    c = gateway.client
    p = _project(gateway)
    created = c.post("/api/ledger/tasks/promote", json={"thread_id": "thread-9", "project_id": p["id"], "titles": ["Draft the post", "Pick a date"]}).json()
    assert [t["title"] for t in created] == ["Draft the post", "Pick a date"]
    attached = c.get("/api/ledger/threads/thread-9/projects").json()
    assert [a["project"]["id"] for a in attached] == [p["id"]]


def test_attach_and_detach_a_conversation(gateway) -> None:
    c = gateway.client
    p = _project(gateway)
    link = c.post("/api/ledger/links", json={"project_id": p["id"], "to_kind": "thread", "to_ref": "thread-1", "label": "Plan the beta"}).json()
    assert c.get("/api/ledger/threads/thread-1/projects").json()[0]["project"]["name"] == "Beta launch"
    assert c.delete(f"/api/ledger/links/{link['id']}").status_code == 204
    assert c.get("/api/ledger/threads/thread-1/projects").json() == []


def test_every_change_records_who_made_it(gateway) -> None:
    """FR-007: the UI's edits are `user`; the assistant's are `assistant_confirmed`."""
    from app.gateway.app import create_app  # noqa: F401  (the app under test is the conftest's)

    p = _project(gateway)
    service = gateway.client.app.state.ledger_service
    changes = service.repo.changes(p["id"])
    assert [(c["actor"], c["before"] is None) for c in changes] == [("user", True)]


def test_another_users_project_is_not_found(gateway) -> None:
    p = _project(gateway)
    service = gateway.client.app.state.ledger_service
    assert service.view(user_id="someone-else", project_id=p["id"]) is None
