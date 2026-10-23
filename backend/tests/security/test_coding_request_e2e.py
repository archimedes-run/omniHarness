"""A coding request, end to end: the file is written, presented, served, and the
dev gateway does not restart because of it.

Real HTTP through create_app(), the real lead agent with its production
middlewares and tools (write_file, present_files); only the model is scripted.
On the live stack a coding task that wrote outputs/*.py restarted the
hot-reloading gateway mid-run (#92): this test maps the file the agent really
wrote onto the dev compose layout and runs uvicorn's own reload filter on it.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import yaml
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from uvicorn.config import Config
from uvicorn.supervisors.watchfilesreload import FileFilter

REPO = Path(__file__).resolve().parents[3]
OUTPUT = "/mnt/user-data/outputs/first_10_primes.py"
SCRIPT = "def primes(n):\n    found = []\n    k = 2\n    while len(found) < n:\n        if all(k % p for p in found):\n            found.append(k)\n        k += 1\n    return found\n\nprint(*primes(10))\n"


class _CodingModel(GenericFakeChatModel):
    """Writes the script, presents it, then answers. Unbound calls (titles,
    suggestions) get plain text so they never consume the script."""

    tools_bound: bool = False

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"tools_bound": True})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        done = [m.name for m in messages if isinstance(m, ToolMessage)]
        if not self.tools_bound:
            reply = AIMessage(content="First 10 primes")
        elif "write_file" not in done:
            reply = AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"description": "Write the script", "path": OUTPUT, "content": SCRIPT}, "id": "w1"}])
        elif "present_files" not in done:
            reply = AIMessage(content="", tool_calls=[{"name": "present_files", "args": {"filepaths": [OUTPUT]}, "id": "p1"}])
        else:
            reply = AIMessage(content="Here is first_10_primes.py.")
        return ChatResult(generations=[ChatGeneration(message=reply)])


def _dev_reload_filter(backend: Path) -> FileFilter:
    command = yaml.safe_load((REPO / "docker/docker-compose-dev.yaml").read_text())["services"]["gateway"]["command"]
    args = shlex.split(re.search(r"uvicorn [^;]*", command).group(0).replace("/app/backend", str(backend)))
    includes = [a.split("=", 1)[1] for a in args if a.startswith("--reload-include=")]
    excludes = [a.split("=", 1)[1] for a in args if a.startswith("--reload-exclude=")]
    return FileFilter(Config(app="app.gateway.app:app", reload=True, reload_dirs=[str(backend)], reload_includes=includes, reload_excludes=excludes))


def test_a_coding_request_writes_presents_and_does_not_reload(sec, monkeypatch, tmp_path) -> None:
    import omniharness.agents.lead_agent.agent as lead_agent
    from omniharness.config.paths import get_paths

    monkeypatch.setattr(lead_agent, "create_chat_model", lambda *a, **k: _CodingModel(messages=iter(())))
    tid = sec.owner.post("/api/threads", json={}).json()["thread_id"]
    resp = sec.owner.post(f"/api/threads/{tid}/runs/wait", json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "human", "content": "Write a Python script that prints the first 10 primes and show me the file."}]}})
    assert resp.status_code == 200, resp.text

    # The panel opens from the thread's artifacts and loads the file through the artifacts route.
    state = sec.owner.get(f"/api/threads/{tid}/state").json()
    assert OUTPUT in state["values"].get("artifacts", []), state["values"].get("artifacts")
    served = sec.owner.get(f"/api/threads/{tid}/artifacts{OUTPUT}")
    assert served.status_code == 200, served.text
    assert served.text == SCRIPT

    # The file the agent wrote, placed where the dev stack keeps it, does not restart the gateway.
    data = get_paths().base_dir
    [written] = [p for p in data.rglob("first_10_primes.py") if "outputs" in p.parts]
    backend = tmp_path / "dev-backend"
    mapped = backend / ".omni-harness" / written.relative_to(data)
    mapped.parent.mkdir(parents=True)
    monkeypatch.chdir(backend)
    assert not _dev_reload_filter(backend)(mapped), f"writing {mapped.relative_to(backend)} restarts the dev gateway"
