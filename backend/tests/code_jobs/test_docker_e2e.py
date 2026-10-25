"""The coding-job Docker end to end (scripts/code-job-e2e.sh): the real sandbox
image with OpenCode, the real egress proxy, the gateway's LLM proxy and job
manager, a scripted provider. Needs Docker and the images:
OMNI_CODE_JOB_DOCKER_E2E=1."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.mark.skipif(os.environ.get("OMNI_CODE_JOB_DOCKER_E2E") != "1", reason="needs Docker and the images: OMNI_CODE_JOB_DOCKER_E2E=1")
def test_code_job_docker_end_to_end() -> None:
    result = subprocess.run(["bash", str(REPO / "scripts/code-job-e2e.sh")], capture_output=True, text=True, timeout=1800)
    lines = [line for line in result.stdout.splitlines() if line.startswith(("ok", "FAIL"))]
    assert result.returncode == 0 and lines and not any(line.startswith("FAIL") for line in lines), "\n".join(lines) + result.stderr[-2000:]
