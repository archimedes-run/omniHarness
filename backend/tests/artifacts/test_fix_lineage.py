"""The automatic fix of a failed html/react version inherits that version's
lineage (service.GatewayArtifactController._fix_lineage).

The live case: the owner asked for a page (v1, user), its checks failed, and
a mid-turn summary replaced the owner's message before the model ran the one
automatic fix (artifact_read of v1, then artifact_update fix_of=1). The walk
then met the summary instead of the owner's message and v2 was stored as
content / "unknown". Each disqualifier below keeps the turn's own lineage.
"""

from __future__ import annotations

import pytest
from fake_sandbox import FakeSandbox, failing
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.gateway.artifacts_store import code_service
from app.gateway.artifacts_store.service import GatewayArtifactController
from app.policy.lineage import TRUSTED_ACK_MARKER, user_turn
from omniharness.agents.turns import TURN_SUMMARY_MARKER
from omniharness.runtime.artifacts.controller import MESSAGES_KEY, TOOL_CALL_KEY

OWNER = "owner-1"
PAGE = "<!doctype html><html><head><style>body{margin:0}</style></head><body><main><h1>Hello</h1></main></body></html>"


def ctx(messages=None, **extra):
    msgs = messages if messages is not None else [user_turn("make a page"), AIMessage(content="", tool_calls=[{"name": "artifact_create", "args": {}, "id": "c1"}])]
    return {"user_id": OWNER, "thread_id": "thread-a", "run_id": "run-1", MESSAGES_KEY: msgs, TOOL_CALL_KEY: "c1", **extra}


@pytest.fixture
def sandbox(monkeypatch):
    box = {"ops": FakeSandbox()}
    monkeypatch.setattr(code_service, "sandbox_factory", lambda thread_id, owner_id: box["ops"])
    return box


@pytest.fixture
def tools(store):
    return GatewayArtifactController(lambda: store)


def create(tools, title="Page"):
    return tools.create(ctx(), kind="html", title=title, content=PAGE, language=None, source_path=None, note=None)


def update(tools, aid, base, content, fix_of=None, messages=None):
    return tools.update(ctx(messages), artifact_id=aid, base_version=base, content=content, edits=None, language=None, note=None, fix_of=fix_of)


def _summary(tools_folded=("artifact_create",), start_found=True):
    record = {"turn_key": "u-1", "tools": list(tools_folded), "start_found": start_found}
    return HumanMessage(content="Summary of the conversation so far.", name="summary", additional_kwargs={TURN_SUMMARY_MARKER: record})


def _read(tools, aid, version, call_id="r1", structured=True):
    text, read = tools.read_bound(ctx(), artifact_id=aid, version=version)
    assert read is not None, text
    return [
        AIMessage(content="", tool_calls=[{"name": "artifact_read", "args": {"id": aid, "version": version}, "id": call_id}]),
        ToolMessage(content=text, tool_call_id=call_id, name="artifact_read", artifact=read if structured else None),
    ]


def _untrusted(name, call_id):
    return [AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": call_id}]), ToolMessage(content="outside text", tool_call_id=call_id, name=name)]


def _ack(call_id="a1"):
    return [
        AIMessage(content="", tool_calls=[{"name": "artifact_update", "args": {}, "id": call_id}]),
        ToolMessage(content="Not changed: pass either content or edits.", tool_call_id=call_id, name="artifact_update", additional_kwargs={TRUSTED_ACK_MARKER: True}),
    ]


def _fix_call():
    return [AIMessage(content="", tool_calls=[{"name": "artifact_update", "args": {}, "id": "u1"}])]


def _failed_v1(tools, sandbox, messages=None, **extra):
    sandbox["ops"].probe = failing(violations=["img-src"])
    text, card = tools.create(ctx(messages, **extra), kind="html", title="Page", content=PAGE, language=None, source_path=None, note=None)
    assert card is not None and "fix_of=1" in text, text
    return card["artifact_id"]


def _fix(tools, aid, messages, base=1, fix_of=1):
    return update(tools, aid, base, content=PAGE.replace("Hello", "Fixed"), fix_of=fix_of, messages=messages)


def _latest(store, aid):
    v = store.versions(OWNER, aid)[0]
    return v["lineage"], v["lineage_source"]


def test_the_live_shape_fix_after_a_summary_inherits_the_owner_origin(tools, store, sandbox):
    aid = _failed_v1(tools, sandbox)
    _, card = _fix(tools, aid, [_summary(), *_read(tools, aid, 1), *_ack(), *_fix_call()])
    assert card is not None and card["version"] == 2
    assert _latest(store, aid) == ("user", None)


def test_the_same_turn_without_fix_of_keeps_todays_lineage(tools, store, sandbox):
    aid = _failed_v1(tools, sandbox)
    update(tools, aid, 1, content=PAGE.replace("Hello", "Fixed"), messages=[_summary(), *_read(tools, aid, 1), *_fix_call()])
    assert _latest(store, aid) == ("content", "unknown")


def test_a_web_fetch_in_the_turn_keeps_content(tools, store, sandbox):
    aid = _failed_v1(tools, sandbox)
    _fix(tools, aid, [_summary(), *_read(tools, aid, 1), *_untrusted("web_fetch", "w1"), *_fix_call()])
    assert _latest(store, aid) == ("content", "web_fetch")


def test_a_web_fetch_folded_into_the_summary_keeps_content_and_is_named(tools, store, sandbox):
    aid = _failed_v1(tools, sandbox)
    _fix(tools, aid, [_summary(("artifact_create", "web_fetch")), *_read(tools, aid, 1), *_fix_call()])
    assert _latest(store, aid) == ("content", "web_fetch")


def test_a_summary_that_never_saw_the_turn_start_keeps_content(tools, store, sandbox):
    aid = _failed_v1(tools, sandbox)
    _fix(tools, aid, [_summary(start_found=False), *_read(tools, aid, 1), *_fix_call()])
    assert _latest(store, aid) == ("content", "unknown")


def test_a_bash_result_keeps_content(tools, store, sandbox):
    aid = _failed_v1(tools, sandbox)
    _fix(tools, aid, [_summary(), *_untrusted("bash", "b1"), *_read(tools, aid, 1), *_fix_call()])
    assert _latest(store, aid) == ("content", "bash")


def test_a_read_of_another_artifact_keeps_content(tools, store, sandbox):
    aid = _failed_v1(tools, sandbox)
    _, other = create(tools, title="Other")
    _fix(tools, aid, [_summary(), *_read(tools, aid, 1), *_read(tools, other["artifact_id"], 1, call_id="r2"), *_fix_call()])
    assert _latest(store, aid) == ("content", "artifact_read")


def test_a_fix_of_an_owner_version_after_a_content_version_still_inherits(tools, store, sandbox):
    # v1 from a page (passing its checks), v2 the owner's change (failed), the fix of v2 also reads v1.
    page_turn = [user_turn("read that page"), *_untrusted("web_fetch", "w1"), AIMessage(content="", tool_calls=[{"name": "artifact_create", "args": {}, "id": "c1"}])]
    aid = tools.create(ctx(page_turn, run_id="run-0"), kind="html", title="Page", content=PAGE, language=None, source_path=None, note=None)[1]["artifact_id"]
    assert _latest(store, aid) == ("content", "web_fetch")
    sandbox["ops"].probe = failing(violations=["img-src"])
    _, v2 = update(tools, aid, 1, content=PAGE.replace("Hello", "Mine"), messages=[user_turn("change it"), AIMessage(content="", tool_calls=[{"name": "artifact_update", "args": {}, "id": "u0"}])])
    assert v2["version"] == 2 and _latest(store, aid) == ("user", None)
    _, card = _fix(tools, aid, [_summary(("artifact_update",)), *_read(tools, aid, 2), *_fix_call()], base=2, fix_of=2)
    assert card is not None and _latest(store, aid) == ("user", None)  # control: the rule applies without the extra read
    store_versions = store.versions(OWNER, aid)
    assert store_versions[0]["n"] == 3


def test_a_read_of_a_content_version_taints_the_fix(tools, store, sandbox):
    page_turn = [user_turn("read that page"), *_untrusted("web_fetch", "w1"), AIMessage(content="", tool_calls=[{"name": "artifact_create", "args": {}, "id": "c1"}])]
    aid = tools.create(ctx(page_turn, run_id="run-0"), kind="html", title="Page", content=PAGE, language=None, source_path=None, note=None)[1]["artifact_id"]
    sandbox["ops"].probe = failing(violations=["img-src"])
    update(tools, aid, 1, content=PAGE.replace("Hello", "Mine"), messages=[user_turn("change it"), AIMessage(content="", tool_calls=[{"name": "artifact_update", "args": {}, "id": "u0"}])])
    _, card = _fix(tools, aid, [_summary(("artifact_update",)), *_read(tools, aid, 2), *_read(tools, aid, 1, call_id="r2"), *_fix_call()], base=2, fix_of=2)
    assert card is not None and _latest(store, aid) == ("content", "artifact_read")


def test_fixing_a_content_version_stays_content_with_its_source(tools, store, sandbox):
    aid = _failed_v1(tools, sandbox, [user_turn("read that page"), *_untrusted("web_fetch", "w1"), AIMessage(content="", tool_calls=[{"name": "artifact_create", "args": {}, "id": "c1"}])])
    _fix(tools, aid, [user_turn("read that page"), *_read(tools, aid, 1), *_fix_call()])
    assert _latest(store, aid) == ("content", "web_fetch")


def test_a_read_without_its_structured_part_keeps_content(tools, store, sandbox):
    aid = _failed_v1(tools, sandbox)
    _fix(tools, aid, [_summary(), *_read(tools, aid, 1, structured=False), *_fix_call()])
    assert _latest(store, aid) == ("content", "artifact_read")


def test_a_fixed_version_from_another_run_is_not_inherited(tools, store, sandbox):
    aid = _failed_v1(tools, sandbox, run_id="run-0")
    _fix(tools, aid, [_summary(), *_read(tools, aid, 1), *_fix_call()])
    assert _latest(store, aid) == ("content", "unknown")


def test_a_forged_fix_of_is_never_trusted(tools, store, sandbox):
    passing_aid = create(tools)[1]["artifact_id"]  # checks pass: no fix allowed
    failed_aid = _failed_v1(tools, sandbox)
    msgs = [_summary(), *_read(tools, passing_aid, 1), *_fix_call()]
    # The model names the passing artifact with a failed version's number: refused, nothing written.
    text, card = _fix(tools, passing_aid, msgs)
    assert card is None and "only for a version whose checks failed" in text
    assert GatewayArtifactController._fix_lineage(store, OWNER, passing_aid, 1, ctx(msgs)) is None
    assert GatewayArtifactController._fix_lineage(store, OWNER, failed_aid, 7, ctx(msgs)) is None
    assert GatewayArtifactController._fix_lineage(store, OWNER, failed_aid, "1; drop", ctx(msgs)) is None
    # A read of the failed artifact does not lend its trust to a fix of the passing one.
    assert GatewayArtifactController._fix_lineage(store, OWNER, failed_aid, 1, ctx([_summary(), *_read(tools, passing_aid, 1), *_fix_call()])) is None
