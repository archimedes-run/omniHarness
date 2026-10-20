"""What the build agent is told about the test pipeline must be true (#59).

The description said the server ran "in an isolated subprocess" and that the
pipeline "verifies required secrets are stored". Neither was true: the test ran
as a plain subprocess of the gateway, and missing secrets never stopped it.
"""

from __future__ import annotations

from omniharness.tools.builtins.mcp_build_tool import mcp_build_tool


def test_the_description_says_what_the_sandbox_really_is() -> None:
    # True since the sandbox test runs in a container (test_mcp_sandbox_escape).
    text = mcp_build_tool.description
    assert "isolated subprocess" not in text
    assert "verifies required secrets are stored" not in text
    assert "locked container (no network, no access to your files" in text
    assert "placeholder keys" in text
