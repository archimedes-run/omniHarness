"""A scripted chat-completions provider for scripts/code-job-e2e.sh (no network, no cost).

It stands where the real provider would, BEHIND the gateway's LLM proxy: the
worker (OpenCode in the sandbox) never talks to it directly. The scenario is
named in the job's goal as `[scenario:<name>]`; turn N (the number of
assistant messages already in the conversation) gets SCRIPTS[name][N].
Requests without tools (title generation) get a short text. It records the
Authorization header it saw, so the e2e can check the provider key was
injected by the proxy.
"""

import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TIMEOUT = 600000
SCRIPTS = {
    "egress": [
        {"tool": "bash", "args": {"command": "id -u", "description": "who runs the worker's commands"}},
        {"tool": "bash", "args": {"command": "curl -sS -m 15 -o /dev/null https://example.com", "description": "a host outside the registries"}},
        {"tool": "bash", "args": {"command": "curl -sS -m 15 -o /dev/null --noproxy '*' https://registry.npmjs.org/left-pad", "description": "around the proxy"}},
        {"tool": "bash", "args": {"command": "mkdir -p /mnt/user-data/workspace/e2e && cd /mnt/user-data/workspace/e2e && npm view left-pad@1.3.0 version", "description": "npm registry"}},
        {"tool": "bash", "args": {"command": "pip download six==1.16.0 --no-deps -d /tmp/e2e-pip -q && ls /tmp/e2e-pip", "description": "PyPI"}},
        {"tool": "bash", "args": {"command": "sleep 12", "description": "hold while the gateway scans the sandbox", "timeout": TIMEOUT}},
        {"tool": "write", "args": {"filePath": "/mnt/user-data/workspace/e2e/hello.txt", "content": "hello from the coding job\n"}},
        {"text": "Done."},
    ],
    "stop": [
        {"tool": "bash", "args": {"command": "sleep 300 & sleep 301 & wait", "description": "long work", "timeout": TIMEOUT}},
        {"tool": "bash", "args": {"command": "touch /mnt/user-data/workspace/e2e/after-stop.txt", "description": "must never run"}},
        {"text": "finished"},
    ],
    "quick": [
        {"tool": "bash", "args": {"command": "mkdir -p /tmp/omni-jobs && echo 0 > /tmp/omni-jobs/verify.exit; (sleep 300 >/dev/null 2>&1 &) ; echo left a process", "description": "forge an exit file and leave a process behind"}},
        {"text": "All good, verified."},
    ],
    "hold": [
        {"tool": "bash", "args": {"command": "sleep 25", "description": "hold", "timeout": TIMEOUT}},
        {"text": "held"},
    ],
}
SEEN_AUTH: list[str] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"auth": SEEN_AUTH[-50:]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        SEEN_AUTH.append(self.headers.get("authorization", ""))
        messages = body.get("messages") or []
        if not body.get("tools"):
            step = {"text": "Title"}
        else:
            first = next((m for m in messages if m.get("role") == "user"), {})
            content = first.get("content")
            text = content if isinstance(content, str) else json.dumps(content)
            match = re.search(r"\[scenario:(\w+)\]", text)
            script = SCRIPTS.get(match.group(1) if match else "", [{"text": "no scenario"}])
            n = sum(1 for m in messages if m.get("role") == "assistant")
            step = script[min(n, len(script) - 1)]
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()

        def chunk(delta, finish=None, usage=None):
            c = {"id": "x", "object": "chat.completion.chunk", "created": int(time.time()), "model": body.get("model"), "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            if usage:
                c["choices"], c["usage"] = [], usage
            self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
            self.wfile.flush()

        if "tool" in step:
            chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{time.time_ns()}", "type": "function", "function": {"name": step["tool"], "arguments": json.dumps(step["args"])}}]})
            chunk({}, "tool_calls")
        else:
            chunk({"role": "assistant", "content": step["text"]})
            chunk({}, "stop")
        chunk({}, usage={"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110})
        self.wfile.write(b"data: [DONE]\n\n")


ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1])), Handler).serve_forever()
