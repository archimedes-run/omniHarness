"""A confirmed action whose tool is missing because its connector toolkit did
not answer within the load limit says so, in plain words, before the claim
(the card stays open to confirm again), never as a bare LookupError.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from omniharness.tools import connector_tools as ct

SEND = "connector-gmail_GMAIL_SEND_EMAIL"
SAID = f"{SEND} was not run: the Gmail connector did not answer in time. Nothing has run. Confirm again to try again."


def _assembly_where_gmail_timed_out(*args, **kwargs):
    ct._note_not_loaded("GMAIL", ct.TIMED_OUT)
    return []


def test_the_words_name_the_connector_and_only_for_a_timeout():
    from app.policy.surface_run import timed_out_reason

    assert timed_out_reason(SEND, [("GMAIL", ct.TIMED_OUT)]) == SAID
    assert timed_out_reason(SEND, [("GMAIL", ct.FAILED)]) is None
    assert timed_out_reason(SEND, [("SLACK", ct.TIMED_OUT)]) is None
    assert timed_out_reason("web_search", [("GMAIL", ct.TIMED_OUT)]) is None


@pytest.mark.anyio
async def test_the_cards_runner_says_the_connector_did_not_answer(monkeypatch):
    import omniharness.tools.tools as tools
    from app.gateway.routers import confirmations

    monkeypatch.setattr(tools, "get_available_tools", _assembly_where_gmail_timed_out)
    run = await confirmations._runner(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())), None, "user-1")
    action = SimpleNamespace(id="a1", surface=None, tool_name=SEND)
    # Before the claim: the card says why and stays open.
    assert run.unavailable(action) == SAID
    # And should it run anyway, the same words, not a bare lookup failure.
    with pytest.raises(LookupError) as raised:
        run(SEND, {})
    assert str(raised.value) == SAID


def test_a_proposing_runs_surface_says_the_connector_did_not_answer(monkeypatch):
    import omniharness.agents.tool_surface as tool_surface
    from app.policy.surface_run import SurfaceSnapshot, unavailable_reason

    monkeypatch.setattr(tool_surface, "tools_for_surface", _assembly_where_gmail_timed_out)
    action = SimpleNamespace(id="a2", surface={"kind": "lead", "config": {}}, tool_name=SEND)
    snapshot = SurfaceSnapshot(None, app_config=SimpleNamespace())
    assert unavailable_reason(action, None, app_config=SimpleNamespace(), snapshot=snapshot) == SAID
