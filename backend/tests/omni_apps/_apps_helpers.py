"""Shared helpers for the Apps tests (a unique module name: `conftest` collides
with other suites' conftest modules when the whole suite is collected)."""

from __future__ import annotations

import json

import httpx

#: A marker no real data contains: tests look for it where it must never be.
MARKER = "ZQX-BRIDGE-MARKER-7731"


class FakeComposio:
    """Composio's execute endpoint, recording every call by slug."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.answers: dict[str, httpx.Response] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        slug = request.url.path.rsplit("/", 1)[-1]
        self.calls.append((slug, json.loads(request.content)))
        if slug in self.answers:
            return self.answers[slug]
        return httpx.Response(200, json={"successful": True, "data": {"items": []}})

    def slugs(self) -> list[str]:
        return [s for s, _ in self.calls]


def gmail_answer(subject: str = f"Invoice {MARKER}", body: str = "SECRET-BODY-TEXT", count: int = 2) -> httpx.Response:
    messages = [
        {
            "messageId": f"18c{i:05d}abcdef",
            "threadId": f"18c{i:05d}abcdef",
            "subject": f"{subject} {i}",
            "sender": "boss@example.com",
            "messageText": body,
            "preview": {"body": body, "subject": f"{subject} {i}"},
            "snippet": body,
            "messageTimestamp": "2026-11-13T09:00:00Z",
            "labelIds": ["UNREAD", "INBOX"],
        }
        for i in range(count)
    ]
    return httpx.Response(200, json={"successful": True, "data": {"messages": messages, "resultSizeEstimate": count}})


INDEX = b"""<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="app.css"></head>
<body><div id="root"></div><script src="app.js"></script></body></html>"""
FILES = {"index.html": INDEX, "app.js": b"document.getElementById('root').textContent = 'hello';", "app.css": b"body{margin:0}"}


def manifest(**sources) -> dict:
    return {"schema": 1, "name": "Today", "description": "My day", "sources": sources or {"inbox": {"use": "gmail.unread_subjects", "fields": ["count", "subject", "received_at", "link"]}}}
