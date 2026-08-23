"""A token minted in one worker must validate in another.

The defect this guards was measured on a real 3-worker uvicorn: three workers,
three distinct tokens, distributing across all three under concurrent load.
Because every internal caller reaches the gateway over HTTP loopback and the
kernel picks the worker, a request had a ~1/N chance of reaching the process
that minted its token and was rejected 401 otherwise.

It hid because light sequential traffic all goes to one accepting worker —
twelve sequential requests landed on a single PID — so it only appears under
concurrency, which is also when it is hardest to attribute.

These tests run the production SHAPE: separate processes, as uvicorn workers
are, rather than one process asserting about itself.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.gateway.internal_auth import INTERNAL_AUTH_TOKEN_ENV

SHARED = "test-shared-internal-token-value"
BACKEND = Path(__file__).resolve().parents[1]


def _worker(snippet: str, env: dict[str, str] | None = None) -> str:
    """Run *snippet* in a fresh interpreter that imports the module itself.

    Deliberately a subprocess rather than multiprocessing: `fork` inherits the
    parent's already-imported module, so a forked child would reuse the token
    the test process minted and prove nothing. A uvicorn worker imports the
    application in its own interpreter, which is what this reproduces.
    """
    environ = {**os.environ, "PYTHONPATH": str(BACKEND)}
    environ.pop(INTERNAL_AUTH_TOKEN_ENV, None)
    environ.update(env or {})
    out = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        env=environ,
        cwd=str(BACKEND),
        timeout=120,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout.strip()


_MINT = "from app.gateway.internal_auth import INTERNAL_AUTH_HEADER_NAME, create_internal_auth_headers;print(create_internal_auth_headers()[INTERNAL_AUTH_HEADER_NAME])"


def _mint(env=None) -> str:
    return _worker(_MINT, env)


def _validate(token: str, env=None) -> bool:
    snippet = f"import sys;from app.gateway.internal_auth import is_valid_internal_auth_token;print(is_valid_internal_auth_token({token!r}))"
    return _worker(snippet, env) == "True"


SHARED_ENV = {INTERNAL_AUTH_TOKEN_ENV: SHARED}


def test_a_token_minted_in_one_worker_validates_in_another():
    """THE claim. Two separate processes, as two workers are."""
    minted = _mint(SHARED_ENV)
    accepted = _validate(minted, SHARED_ENV)

    assert accepted, "a token minted in one worker was rejected by another. Internal loopback calls — channel messages and trigger injection — will 401 whenever the kernel routes them to a different worker."


def test_all_workers_mint_the_same_token():
    """Not merely mutually acceptable — identical, so the failure cannot depend
    on which worker happens to answer."""
    tokens = {_mint(SHARED_ENV) for _ in range(3)}

    assert len(tokens) == 1, f"{len(tokens)} distinct tokens across 3 workers; all must agree"


def test_without_the_env_var_workers_disagree():
    """Pins the defect itself, so the fallback is never mistaken for safe under
    multiple workers.

    A generated token is correct for a single process, which both mints and
    validates. It is exactly wrong for several.
    """
    tokens = {_mint() for _ in range(3)}

    assert len(tokens) == 3, "the generated fallback now agrees across processes — if it has become deterministic, that is a weaker secret, not a fix"


def test_a_foreign_token_is_still_rejected():
    """The change must not make validation permissive."""
    assert not _validate("not-the-token", SHARED_ENV)
    assert not _validate("", SHARED_ENV)


def test_the_shared_token_is_reported_as_shared():
    """Operators and the readiness check need to distinguish 'configured' from
    'generated', because the two are indistinguishable from a single worker."""
    check = "from app.gateway.internal_auth import internal_auth_is_shared;print(internal_auth_is_shared())"

    assert _worker(check, SHARED_ENV) == "True"
    assert _worker(check) == "False", "a generated fallback must not report itself as shared"


def test_multi_worker_deployments_must_set_it():
    """Readiness: the compose stack runs several workers, so it must supply the
    variable rather than relying on the single-process fallback."""
    from pathlib import Path

    compose = Path(__file__).resolve().parents[2] / "docker" / "docker-compose.yaml"
    if not compose.exists():  # pragma: no cover
        pytest.skip("compose file not found")
    text = compose.read_text()
    if "--workers" not in text:
        pytest.skip("compose no longer runs multiple workers")

    assert INTERNAL_AUTH_TOKEN_ENV in text, f"docker-compose runs multiple workers but never sets {INTERNAL_AUTH_TOKEN_ENV}; each worker would mint its own token and internal calls would 401 across workers"


def test_env_var_wins_over_generation():
    """The configured value is used verbatim, not mixed with a generated one."""
    assert _mint(SHARED_ENV) == SHARED
