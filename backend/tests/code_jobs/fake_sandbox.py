"""A stand-in for the thread's container sandbox that plays OpenCode's
`run --format json` events, for the coding-job HTTP tests.

It implements the job manager's SandboxOps seam only; everything above it
(the tool, the manager, verification, the store, the routes, Stop) is the
production code. The real sandbox, OpenCode and proxy are exercised by
scripts/code-job-e2e.sh.
"""

from __future__ import annotations

import json
import re
import shlex
import threading
import time

EXCLUDE = ("node_modules", ".git", "dist", "build", ".next", "coverage", ".cache", ".vite", "__pycache__", ".venv")


def bash(command: str, exit_code: int = 0, output: str = "", creates: dict[str, str] | None = None, delay: float = 0.05) -> dict:
    return {"kind": "bash", "command": command, "exit": exit_code, "output": output, "creates": creates or {}, "delay": delay}


def write(path: str, content: str, delay: float = 0.05) -> dict:
    return {"kind": "write", "path": path, "content": content, "delay": delay}


def text(t: str, delay: float = 0.05) -> dict:
    return {"kind": "text", "text": t, "delay": delay}


def error(message: str, delay: float = 0.05) -> dict:
    return {"kind": "error", "message": message, "delay": delay}


def sleep(seconds: float) -> dict:
    return {"kind": "sleep", "delay": seconds}


class FakeSandbox:
    def __init__(self, scenario: list[dict], *, container: str = "omni-harness-sandbox-test0001", verify_exit: int | None = 0, verify_log: str = "built", kill_works: bool = True, stderr: str = "") -> None:
        self.container = container
        self.scenario = scenario
        self.verify_exit = verify_exit
        self.verify_log = verify_log
        self.kill_works = kill_works
        self.stderr = stderr
        self.fs: dict[str, str] = {}
        self.mtime: dict[str, float] = {}
        self.killed = threading.Event()
        self.kill_calls = 0
        self.token_seen: str | None = None
        self.run_script: str | None = None
        self.lock = threading.Lock()
        self.emitted = 0
        self.finished = threading.Event()
        self.before_exit = None
        self.verify_runs = 0
        self.verify_env = ""

    # -- filesystem --------------------------------------------------------------

    def _put(self, path: str, content: str) -> None:
        with self.lock:
            self.fs[path] = content
            self.mtime[path] = time.time()

    def write(self, path: str, content: str) -> None:
        self._put(path, content)

    def read_text(self, path: str) -> str | None:
        with self.lock:
            return self.fs.get(path)

    def read_lines(self, path: str, start: int, count: int) -> list[str] | None:
        with self.lock:
            content = self.fs.get(path)
        if content is None:
            return None
        lines = content.split("\n")
        if content.endswith("\n"):
            lines = lines[:-1]
        return lines[start : start + count]

    def _append_event(self, path: str, event: dict) -> None:
        with self.lock:
            self.fs[path] = self.fs.get(path, "") + json.dumps(event) + "\n"
            self.emitted += 1

    # -- commands ----------------------------------------------------------------

    def sh(self, command: str, *, timeout: int = 30) -> tuple[int | None, str]:
        if "kill -TERM" in command:
            self.kill_calls += 1
            if self.kill_works:
                self.killed.set()
            return 0, "__killed__"
        if "timeout -k 5" in command and "verify.log" in command:
            log = re.search(r"> (\S+verify\.log)", command).group(1).strip("'")
            self._put(log, self.verify_log)
            self.verify_runs += 1
            self.verify_env = command
            return (self.verify_exit if self.verify_exit is not None else 124), ""
        if "find . " in command and "-printf" in command:
            project = re.search(r"cd (\S+) 2>/dev/null", command).group(1).strip("'")
            out = re.search(r"head -n 5000 > (\S+?);", command).group(1).strip("'")
            rows = []
            with self.lock:
                for path, content in self.fs.items():
                    if path.startswith(project + "/"):
                        rel = path[len(project) + 1 :]
                        if any(part in EXCLUDE for part in rel.split("/")):
                            continue
                        rows.append(f"{rel}\t{len(content)}\t{self.mtime[path]:.3f}")
            self._put(out, "\n".join(rows) + ("\n" if rows else ""))
            return 0, ""
        if "stat -c %s" in command:
            path = shlex.split(command)[2]
            content = self.read_text(path)
            return 0, str(len(content)) if content else "__missing__"
        if "__y__" in command:
            path = shlex.split(command)[2]
            return 0, "__y__" if path in self.fs else "__n__"
        if "__ok__" in command:
            parts = shlex.split(command)
            source = parts[2].rsplit("/index.html", 1)[0]
            target = parts[parts.index("mkdir") + 2]
            with self.lock:
                items = [(p, c) for p, c in self.fs.items() if p.startswith(source + "/")]
            if not any(p == source + "/index.html" and c for p, c in items):
                return 1, ""
            for path, content in items:
                self._put(target + path[len(source) :], content)
            return 0, "__ok__"
        if command.startswith("rm -rf "):
            prefix = shlex.split(command)[2]
            with self.lock:
                for path in [p for p in self.fs if p.startswith(prefix)]:
                    del self.fs[path]
            return 0, ""
        return 0, ""

    def start(self, session_id: str, command: str) -> None:
        script_path = shlex.split(command)[1]
        d = script_path.rsplit("/", 1)[0]
        if script_path.endswith("/run.sh"):
            self.run_script = self.read_text(script_path)
            threading.Thread(target=self._play, args=(d,), daemon=True).start()
        elif script_path.endswith("/verify.sh"):
            threading.Thread(target=self._verify, args=(d,), daemon=True).start()

    def _play(self, d: str) -> None:
        self.token_seen = self.read_text(f"{d}/token")
        with self.lock:
            self.fs.pop(f"{d}/token", None)  # run.sh: rm -f token
        self._put(f"{d}/pgid", "4242\n")
        events = f"{d}/events.jsonl"
        self._put(events, "")
        call = 0
        for item in self.scenario:
            if self.killed.wait(item["delay"]):
                return
            call += 1
            if item["kind"] == "sleep":
                continue
            if item["kind"] == "bash":
                for path, content in item["creates"].items():
                    self._put(path, content)
                state = {"status": "completed", "input": {"command": item["command"]}, "output": item["output"], "metadata": {"output": item["output"], "exit": item["exit"]}}
                self._append_event(events, {"type": "tool_use", "part": {"type": "tool", "tool": "bash", "callID": f"c{call}", "state": state}})
            elif item["kind"] == "write":
                self._put(item["path"], item["content"])
                state = {"status": "completed", "input": {"filePath": item["path"], "content": item["content"]}, "metadata": {"filepath": item["path"]}}
                self._append_event(events, {"type": "tool_use", "part": {"type": "tool", "tool": "write", "callID": f"c{call}", "state": state}})
            elif item["kind"] == "text":
                self._append_event(events, {"type": "text", "part": {"type": "text", "text": item["text"], "time": {"end": 1}}})
            elif item["kind"] == "error":
                self._append_event(events, {"type": "error", "error": {"name": "APIError", "data": {"message": item["message"]}}})
            self._append_event(events, {"type": "step_finish", "part": {"type": "step-finish", "tokens": {"input": 1000, "output": 100}}})
        if self.killed.is_set():
            return
        self._put(f"{d}/stderr.txt", self.stderr)
        if self.before_exit is not None:
            self.before_exit()
        self._put(f"{d}/exit", "0\n")
        self.finished.set()

    def _verify(self, d: str) -> None:
        time.sleep(0.1)
        self._put(f"{d}/verify.log", self.verify_log)
        if self.verify_exit is not None:
            self._put(f"{d}/verify.exit", f"{self.verify_exit}\n")

    def end_session(self, session_id: str) -> None:
        pass

    def touch(self) -> None:
        pass
