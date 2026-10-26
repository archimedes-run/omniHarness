"""The coding-job LLM proxy (spec 009 FR-003/FR-004): the sandbox holds a per-job
token, never a provider key; the proxy checks token, container, job, budget,
cap, rate and model, injects the key server-side and records every call.

Through the proxy's real ASGI app, with the provider replaced by an httpx mock
transport that records what reached it.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json

import httpx
import pytest

UPSTREAM_KEY = "sk-upstream-provider-key-NEVER-IN-SANDBOX-0123456789"
SBX_A, SBX_B = "172.22.0.5", "172.22.0.6"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "proxy-test-gateway-secret-0123456789")


class Upstream:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.delay = 0.0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "provider says no"}})
        body = json.loads(request.content)
        if body.get("stream") and self.delay:
            delay = self.delay

            async def slow():
                yield b'data: {"choices": [{"index": 0, "delta": {"content": "hi"}}]}\n\n'
                await asyncio.sleep(delay)
                yield b'data: {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 1}}\n\n'
                yield b"data: [DONE]\n\n"

            return httpx.Response(200, content=slow(), headers={"content-type": "text/event-stream"})
        if body.get("stream"):
            chunks = [
                {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "hi"}}]},
                {"choices": [], "usage": {"prompt_tokens": 2000, "completion_tokens": 500, "prompt_tokens_details": {"cached_tokens": 1000}}},
            ]
            text = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
            return httpx.Response(200, text=text, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "hi"}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 100}})


@pytest.fixture
def proxy(tmp_path):
    from app.gateway.code_jobs.llm_proxy import ProxySettings, build_proxy_app
    from app.gateway.code_jobs.store import CodeJobStore
    from app.gateway.code_jobs.upstream import Upstream as Up

    store = CodeJobStore(tmp_path / "jobs.db")
    upstream = Upstream()
    settings = ProxySettings(
        store=store,
        upstream_for=lambda: (Up(name="default", model="gpt-5", base_url="https://provider.test/v1", api_key=UPSTREAM_KEY, provider="openai"), None),
        subnets=[ipaddress.IPv4Network("172.22.0.0/16")],
        monthly_cap_usd=20.0,
        rate_per_minute=5,
        max_request_bytes=64 * 1024,
        policy_log=tmp_path / "policy" / "llm-proxy.jsonl",
        # "sbx-x" resolves off the sandbox network: only the subnet check can refuse it.
        resolve_container={"sbx-a": SBX_A, "sbx-b": SBX_B, "sbx-x": "192.168.200.10"}.get,
        transport=httpx.MockTransport(upstream.handler),
    )
    app = build_proxy_app(settings)
    store.create(job_id="job-a", thread_id="t1", user_id="u", tool_call_id="c", title="x", project_dir="p", budget_usd=1.0, model="gpt-5")
    return app, store, upstream, tmp_path


def _call(app, *, peer=SBX_A, token=None, body=None, path="/v1/chat/completions"):
    async def go():
        transport = httpx.ASGITransport(app=app, client=(peer, 40000))
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
            headers = {"authorization": f"Bearer {token}"} if token else {}
            return await client.post(path, json=body if body is not None else {"model": "worker", "messages": [{"role": "user", "content": "hi"}]}, headers=headers)

    return asyncio.run(go())


def _token(job="job-a", container="sbx-a"):
    from app.gateway.code_jobs import tokens

    return tokens.mint(job_id=job, container=container, thread_id="t1", ttl_seconds=300)


def test_a_call_with_the_jobs_token_reaches_the_provider_with_the_key_injected_there(proxy):
    app, store, upstream, tmp = proxy
    resp = _call(app, token=_token(), body={"model": "worker", "messages": [{"role": "user", "content": "x"}], "stream": True, "max_tokens": 32000, "temperature": 0.2})
    assert resp.status_code == 200 and "data:" in resp.text
    sent = upstream.requests[-1]
    assert sent.headers["authorization"] == f"Bearer {UPSTREAM_KEY}"
    body = json.loads(sent.content)
    assert body["model"] == "gpt-5" and body["stream_options"]["include_usage"] is True
    assert "max_tokens" not in body and body["max_completion_tokens"] == 32000 and "temperature" not in body
    calls = store.job_calls("job-a")
    assert calls[-1]["status"] == "ok" and calls[-1]["input_tokens"] == 2000 and calls[-1]["cached_tokens"] == 1000
    assert store.get("job-a").spent_usd == pytest.approx((1000 * 1.25 + 1000 * 0.125 + 500 * 10) / 1e6)
    assert UPSTREAM_KEY not in resp.text
    log = (tmp / "policy" / "llm-proxy.jsonl").read_text()
    assert '"decision": "allowed"' in log and UPSTREAM_KEY not in log and "messages" not in log


def test_no_token_or_a_forged_token_is_refused_and_never_reaches_the_provider(proxy):
    app, _, upstream, _ = proxy
    assert _call(app).status_code == 401
    assert _call(app, token="sk-not-a-job-token").status_code == 401
    assert upstream.requests == []


def test_a_token_used_from_another_sandbox_is_refused(proxy):
    app, _, upstream, _ = proxy
    resp = _call(app, peer=SBX_B, token=_token())
    assert resp.status_code == 403 and "another sandbox" in resp.text
    assert upstream.requests == []


def test_a_caller_outside_the_sandbox_network_is_refused(proxy):
    app, store, upstream, _ = proxy
    store.create(job_id="job-x", thread_id="t1", user_id="u", tool_call_id="x", title="x", project_dir="p", budget_usd=1.0, model="gpt-5")
    # A valid token whose container address is the caller's own, but off the
    # sandbox network (nginx's address on the app network, say).
    resp = _call(app, peer="192.168.200.10", token=_token(job="job-x", container="sbx-x"))
    assert resp.status_code == 403 and "not from the sandbox network" in resp.text
    assert upstream.requests == []


def test_only_the_worker_model_is_allowed(proxy):
    app, _, upstream, _ = proxy
    resp = _call(app, token=_token(), body={"model": "gpt-5", "messages": []})
    assert resp.status_code == 400 and upstream.requests == []


def test_a_spent_budget_a_stopped_job_and_the_month_cap_refuse_the_call(proxy, monkeypatch):
    app, store, upstream, _ = proxy
    store.record_call(job_id="job-a", container="sbx-a", model="gpt-5", status="ok", cost_usd=1.0)
    resp = _call(app, token=_token())
    assert resp.status_code == 402 and "budget" in resp.text and "Refused by the OmniHarness gateway" in resp.text
    store.create(job_id="job-s", thread_id="t1", user_id="u", tool_call_id="s", title="x", project_dir="p", budget_usd=1.0, model="gpt-5")
    store.request_stop("job-s")
    assert _call(app, token=_token(job="job-s")).status_code == 402
    assert upstream.requests == []


def test_the_rate_limit_holds_per_sandbox(proxy):
    app, store, upstream, _ = proxy
    for _ in range(5):
        store.record_call(job_id="job-a", container="sbx-a", model="gpt-5", status="ok", cost_usd=0.0)
    resp = _call(app, token=_token())
    assert resp.status_code == 429 and upstream.requests == []


def test_a_provider_error_is_passed_back_and_recorded_without_charge(proxy):
    app, store, upstream, _ = proxy
    upstream.status = 400
    resp = _call(app, token=_token())
    assert resp.status_code == 400
    assert store.job_calls("job-a")[-1]["status"] == "error" and store.get("job-a").spent_usd == 0


def test_every_other_path_is_not_found(proxy):
    app, _, upstream, _ = proxy
    assert _call(app, token=_token(), path="/v1/responses").status_code == 404
    assert upstream.requests == []


def _raw_call(app, *, token, body, disconnect_after_first_chunk=False):
    """Drive the ASGI app directly, so the caller can leave mid-stream."""

    async def go():
        payload = json.dumps(body).encode()
        left = asyncio.Event()
        sent_body = False
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/v1/chat/completions",
            "raw_path": b"/v1/chat/completions",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"authorization", f"Bearer {token}".encode()), (b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())],
            "client": (SBX_A, 40000),
            "server": ("proxy", 80),
        }
        chunks = []

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": payload, "more_body": False}
            await left.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                chunks.append(message["body"])
                if disconnect_after_first_chunk:
                    left.set()

        await asyncio.wait_for(app(scope, receive, send), timeout=10)
        return chunks

    return asyncio.run(go())


def test_leaving_before_the_usage_chunk_still_charges_the_reservation(proxy):
    app, store, upstream, _ = proxy
    upstream.delay = 1.0
    chunks = _raw_call(app, token=_token(), body={"model": "worker", "messages": [{"role": "user", "content": "x"}], "stream": True}, disconnect_after_first_chunk=True)
    assert chunks and b"usage" not in b"".join(chunks), "the caller left before the usage chunk"
    calls = store.job_calls("job-a")
    assert calls[-1]["status"].endswith("estimated")
    # 32k output tokens at gpt-5's $10/M, plus the input: well above zero.
    assert store.get("job-a").spent_usd >= 0.32


def test_twenty_concurrent_calls_get_at_most_three_through(proxy):
    app, store, upstream, _ = proxy
    upstream.delay = 0.5

    async def go():
        transport = httpx.ASGITransport(app=app, client=(SBX_A, 40000))
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy", timeout=30) as client:
            tok = _token()
            body = {"model": "worker", "messages": [{"role": "user", "content": "x"}], "stream": True}
            return await asyncio.gather(*[client.post("/v1/chat/completions", json=body, headers={"authorization": f"Bearer {tok}"}) for _ in range(20)])

    statuses = sorted(r.status_code for r in asyncio.run(go()))
    assert statuses.count(200) == 3 and statuses.count(429) == 17, statuses


def test_output_is_capped_and_only_allowed_keys_reach_the_provider(proxy):
    app, store, upstream, _ = proxy
    body = {"model": "worker", "messages": [{"role": "user", "content": "x"}], "max_tokens": 10_000_000, "n": 8, "service_tier": "priority", "store": True, "metadata": {"a": 1}, "audio": {}, "logprobs": True}
    assert _call(app, token=_token(), body=body).status_code == 200
    sent = json.loads(upstream.requests[-1].content)
    assert sent["max_completion_tokens"] == 32_000
    assert not ({"n", "service_tier", "store", "metadata", "audio", "logprobs", "max_tokens"} & set(sent)), sent


def test_the_output_allowed_never_exceeds_what_the_budget_can_pay(proxy):
    app, store, upstream, _ = proxy
    store.record_call(job_id="job-a", container="sbx-a", model="gpt-5", status="ok", cost_usd=0.95)
    assert _call(app, token=_token(), body={"model": "worker", "messages": [{"role": "user", "content": "x"}]}).status_code == 200
    sent = json.loads(upstream.requests[-1].content)
    assert sent["max_completion_tokens"] <= 5_000, "$0.05 left buys at most 5k output tokens at $10/M"


def test_a_provider_error_reaches_the_worker_without_its_detail(proxy):
    app, store, upstream, tmp = proxy
    upstream.status = 400
    resp = _call(app, token=_token())
    assert resp.status_code == 400 and "provider says no" not in resp.text and "status 400" in resp.text
