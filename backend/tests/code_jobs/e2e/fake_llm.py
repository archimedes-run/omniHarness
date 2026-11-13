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
W = "/mnt/user-data/workspace"
#: Web apps for the layout check: one that fits, and one per failure it must catch.
FIT_HTML = (
    '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>'
    "body{margin:0;font-family:sans-serif}.board{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px;padding:8px}"
    ".col{background:#eee;min-height:80px}.donut svg{width:100%;max-width:240px;height:auto}</style></head><body><h1>Board</h1>"
    '<div class="board"><div class="col">To do</div><div class="col">Doing</div><div class="col">Done</div></div>'
    '<div class="donut"><svg viewBox="0 0 120 120"><circle cx="60" cy="60" r="45" fill="none" stroke="#36c" stroke-width="20"/>'
    '<text x="60" y="65" text-anchor="middle">42%</text></svg></div></body></html>'
)
OVERFLOW_HTML = (
    "<!doctype html><html><head><style>body{margin:0}.board{display:flex;gap:8px}.col{flex:0 0 300px;background:#eee;min-height:80px}</style></head>"
    '<body><h1>Board</h1><div class="board"><div class="col">To do</div><div class="col">Doing</div><div class="col">Done</div></div></body></html>'
)
CLIPPED_HTML = (
    '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}</style></head>'
    '<body><p>Stats</p><div class="donut"><svg width="100" height="100" viewBox="0 0 100 100">'
    '<circle cx="50" cy="50" r="50" fill="none" stroke="#36c" stroke-width="24"/></svg></div></body></html>'
)
BLANK_HTML = '<!doctype html><html><body><div id="root"></div><script>throw new Error("boom: cannot read properties of undefined")</script></body></html>'


def app(project: str, html: str) -> list:
    return [{"tool": "write", "args": {"filePath": f"{W}/{project}/dist/index.html", "content": html}}, {"text": "Built the app; it is responsive."}]


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
        {
            "tool": "bash",
            "args": {
                "command": (
                    "mkdir -p /mnt/user-data/workspace/e2e && cd /mnt/user-data/workspace/e2e && echo 0 > verify.exit; "
                    "(sleep 300 >/dev/null 2>&1 &) ; (setsid env -i sh -c 'sleep 999' >/dev/null 2>&1 &) ; "
                    "tmux -L privatex new -d 'sleep 888' ; S=$(command -v sleep) ; cp \"$S\" ./tmuxanything && (setsid ./tmuxanything 889 >/dev/null 2>&1 &) ; echo left processes"
                ),
                "description": "forge an exit file and leave processes behind",
            },
        },
        {"tool": "bash", "args": {"command": "sleep 1; pgrep -fc '[s]leep 999|[s]leep 888|[t]muxanything 889'", "description": "the leftovers are alive while the worker runs"}},
        {"text": "All good, verified."},
    ],
    "layout_fit": app("layout-fit", FIT_HTML),
    "layout_overflow": app("layout-overflow", OVERFLOW_HTML),
    "layout_clipped": app("layout-clipped", CLIPPED_HTML),
    "layout_blank": app("layout-blank", BLANK_HTML),
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
