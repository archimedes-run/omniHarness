"""Shared constants and the login helper for the security-baseline tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

OWNER = ("owner@example.com", "Str0ng!Pass99")
SECOND = ("second@example.com", "An0ther!Pass77")


def _with_csrf(client: TestClient) -> TestClient:
    csrf = client.cookies.get("csrf_token")
    if csrf:
        client.headers["X-CSRF-Token"] = csrf
    return client


def login(app, email: str, password: str) -> tuple[TestClient, object]:
    """A fresh client (its own cookie jar) and the login response."""
    client = TestClient(app)
    resp = client.post("/api/v1/auth/login/local", data={"username": email, "password": password})
    return _with_csrf(client), resp
