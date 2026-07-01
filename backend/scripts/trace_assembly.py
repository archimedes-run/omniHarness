"""One end-to-end trace of a single assembled turn (review artifact + fixture).

Prints: user_id, the thread selection going in, and the final deduped tool
array coming out (with namespaces) plus the count against the provider cap.
"""

import asyncio
import os

from omniharness.config import get_app_config
from omniharness.persistence.engine import get_session_factory, init_engine_from_config
from omniharness.persistence.thread_tool_selection import ThreadToolSelectionRepository
from omniharness.tools.tools import get_available_tools, resolve_model_tool_cap

USER_ID = os.environ.get("TRACE_USER_ID", "09741403-89cb-49f9-a306-7e8b2d49df40")
THREAD_ID = os.environ.get("TRACE_THREAD_ID", "trace-thread-1")
# Includes a bogus connector (SLACK, not connected) and a bogus local server to
# prove unresolvable selections are silently dropped (constraint #2).
DESIRED = ["local:github", "connector:GMAIL", "connector:GOOGLECALENDAR", "connector:SLACK", "local:does_not_exist"]


async def main() -> None:
    cfg = get_app_config()
    await init_engine_from_config(cfg.database)
    sf = get_session_factory()

    repo = ThreadToolSelectionRepository(sf)
    stored = await repo.set_sources(thread_id=THREAD_ID, user_id=USER_ID, sources=DESIRED)

    model_config = cfg.models[0] if cfg.models else None
    cap = resolve_model_tool_cap(model_config)

    # Assembly runs in a worker thread (get_available_tools is sync and spawns
    # connector subprocesses); run it off the event loop.
    loop = asyncio.get_running_loop()
    tools = await loop.run_in_executor(
        None,
        lambda: get_available_tools(
            selected_sources=set(stored),
            user_id=USER_ID,
            app_config=cfg,
        ),
    )
    names = sorted(t.name for t in tools)

    def _bucket(prefix):
        return [n for n in names if n.startswith(prefix)]

    print("=" * 72)
    print("END-TO-END ASSEMBLED-TURN TRACE")
    print("=" * 72)
    print(f"user_id          : {USER_ID}")
    print(f"thread_id        : {THREAD_ID}")
    print(f"desired (client) : {DESIRED}")
    print(f"stored (pinned+) : {stored}")
    print(f"model / cap      : {getattr(model_config, 'name', '?')} / {cap}")
    print("-" * 72)
    print(f"assembled count  : {len(tools)}  (cap {cap} -> {'OVER' if len(tools) > cap else 'ok'})")
    print(f"  connector-gmail   : {len(_bucket('connector-gmail'))}")
    print(f"  connector-google  : {len(_bucket('connector-googlecalendar'))}")
    print(f"  connector-slack   : {len(_bucket('connector-slack'))}  (expected 0 — not connected)")
    print(f"  local github      : {len(_bucket('github_'))}")
    print(f"  local filesystem  : {len(_bucket('filesystem_'))} (pinned)")
    print(f"  local postgres    : {len(_bucket('postgres_'))} (pinned)")
    print("-" * 72)
    print("sample tool ids (namespaced), first 24:")
    for n in names[:24]:
        print(f"    {n}")


if __name__ == "__main__":
    asyncio.run(main())
