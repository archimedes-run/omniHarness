"""Step: execution mode and safety-related capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from wizard.ui import ask_choice, ask_yes_no, print_header, print_info, print_warning

LOCAL_SANDBOX = "omniharness.sandbox.local:LocalSandboxProvider"
CONTAINER_SANDBOX = "omniharness.community.aio_sandbox:AioSandboxProvider"


@dataclass
class ExecutionStepResult:
    sandbox_use: str
    include_bash_tool: bool
    include_write_tools: bool


def run_execution_step(step_label: str = "Step 3/4") -> ExecutionStepResult:
    print_header(f"{step_label} · Execution & Safety")
    print_info("Choose how much execution power OmniHarness should have in this workspace.")

    options = [
        "Local sandbox  —  fastest, uses host filesystem paths",
        "Container sandbox  —  more isolated, requires Docker or Apple Container",
    ]
    sandbox_idx = ask_choice("Execution mode", options, default=0)
    sandbox_use = LOCAL_SANDBOX if sandbox_idx == 0 else CONTAINER_SANDBOX

    print()
    if sandbox_use == LOCAL_SANDBOX:
        print_warning(
            "Local sandbox is convenient but not a secure shell isolation boundary."
        )
        print_info("Commands never run on the host: bash needs the container sandbox.")
    else:
        print_info("Container sandbox isolates shell execution better than host-local mode.")

    include_bash_tool = sandbox_use == CONTAINER_SANDBOX and ask_yes_no("Enable bash command execution (in the container)?", default=False)
    include_write_tools = ask_yes_no(
        "Enable file write tools (write_file, str_replace)?", default=True
    )

    return ExecutionStepResult(
        sandbox_use=sandbox_use,
        include_bash_tool=include_bash_tool,
        include_write_tools=include_write_tools,
    )
