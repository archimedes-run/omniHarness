"""No docker command the gateway issues can reach a registry (#59).

The one approved download (the digest-pinned Alpine base) is pulled by a
person; the gateway never pulls, and a missing image is an error."""

from __future__ import annotations

import asyncio

import pytest
from mcp_build_helpers import enable, wait_for

from app.gateway.mcp_docker import CliDockerRunner, RegistryContactError, check_no_registry


@pytest.mark.parametrize(
    "args",
    [
        ["docker", "pull", "alpine"],
        ["docker", "push", "x"],
        ["docker", "login"],
        ["docker", "run", "--rm", "python:3.12-slim"],
        ["docker", "create", "--name", "x", "img"],
        ["docker", "build", "-t", "x", "-"],
        ["docker", "build", "--pull", "-t", "x", "-"],
    ],
)
def test_commands_that_could_reach_a_registry_are_refused(args) -> None:
    with pytest.raises(RegistryContactError):
        check_no_registry(args)
    with pytest.raises(RegistryContactError):
        asyncio.run(CliDockerRunner().run(args))  # refused before any process starts


def test_every_run_and_create_the_deploy_issues_says_pull_never(built) -> None:
    gw, sid, runner, manager = built
    assert enable(gw, sid).status_code == 200
    wait_for(gw, sid, {"enabled"})
    issued = [c.args for c in runner.calls if c.args[1] in ("run", "create", "build", "pull")]
    assert issued, "the deploy issued no run/create"
    for args in issued:
        check_no_registry(args)
    # The sandbox test's docker run (spawned by the MCP stdio client) too.
    check_no_registry(["docker", *manager._sandbox_args("n", sid, "sha256:" + "0" * 64)])


def test_a_missing_base_image_is_an_error_not_a_download(tmp_path) -> None:
    from mcp_fakes import FakeDockerRunner

    from app.gateway.mcp_runtime_image import RuntimeImageError, RuntimeImages

    runner = FakeDockerRunner()
    runner.results["image"] = (1, "", "No such image")
    images = RuntimeImages(runner, state_dir=tmp_path)
    with pytest.raises(RuntimeImageError, match="does not download"):
        asyncio.run(images.egress_image_id())
    assert not any(c.args[1] in ("pull", "build") for c in runner.calls)
