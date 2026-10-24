"""Only the owner changes an agent's tools, avatar or delivery defaults (006-G).

Real HTTP through `create_app()` (the `sec` fixture). With the shipped door
closed a second account cannot even sign in; this opens it (`admit_second`)
to prove the per-user agent store keeps the owner's agent out of its reach on
its own. The agent stays exactly as the owner left it, and the owner-only
Studio read (the tool catalog) answers only the owner.
"""

from __future__ import annotations

ACCESS = {"integrations": ["builtin:web"], "tools": ["web_search"]}


def _owners_agent(sec) -> dict:
    created = sec.owner.post("/api/agents", json={"name": "owners-agent", "soul": "be useful", "avatar": "pip", "tools": ACCESS})
    assert created.status_code == 201, created.text
    return created.json()


def _unchanged(sec) -> None:
    got = sec.owner.get("/api/agents/owners-agent").json()
    assert (got["avatar"], got["tools"]) == ("pip", ACCESS), got


def test_with_the_door_open_the_owners_agent_is_still_out_of_reach(sec) -> None:
    agent = _owners_agent(sec)
    sec.admit_second()
    other = sec.login_second()
    widened = {"integrations": ["builtin:web", "builtin:bash"], "tools": ["web_search", "bash"]}
    resp = other.put("/api/agents/owners-agent", json={"tools": widened, "avatar": "boo", "base_version": agent["version"]})
    assert resp.status_code == 404, resp.text
    # Creating its own agent of the same name does not touch the owner's.
    mine = other.post("/api/agents", json={"name": "owners-agent", "tools": widened})
    assert mine.status_code in (201, 409), mine.text
    assert other.get("/api/studio/tool-catalog").status_code in (401, 403, 404), "the owner-only tool catalog answered another account"
    _unchanged(sec)
