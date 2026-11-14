"""CodeJobController port and the brief/outcome shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

#: The rules every coding job runs under (FR-006). Tracked here, written into
#: the job's workspace, and baked into the sandbox image as
#: /etc/opencode/AGENTS.md (docker/sandbox/opencode/AGENTS.md is a byte copy;
#: a test keeps the two identical).
RULES_PATH = Path(__file__).with_name("AGENTS.md")
RULES_MARKER = "<!-- omni-harness:coding-job-rules"


def rules_text() -> str:
    return RULES_PATH.read_text(encoding="utf-8")


@dataclass(frozen=True)
class CodeJobBrief:
    """What the lead asks for (FR-030's fields, Slice 1 shape)."""

    goal: str
    project_dir: str
    done_criteria: list[str] = field(default_factory=list)
    inputs: str = ""
    constraints: str = ""
    verify_command: str | None = None
    expect_files: list[str] = field(default_factory=list)
    publish_dir: str | None = None
    title: str = ""
    #: The one automatic layout fix: the id of the job whose layout check
    #: failed. The gateway allows one per job, never a fix of a fix.
    fix_of: str | None = None
    #: App mode (Spec 011 FR-025): `{"name", "description"?, "timezone"?,
    #: "sources"}`. The gateway validates it against the source catalog,
    #: writes the app kit, checks the mock build and registers a passing app
    #: for the person's approval. None: an ordinary job. With `fix_of` on an
    #: app job, the follow-up is one of the app's design passes (at most 3).
    app: dict | None = None


@dataclass
class CodeJobOutcome:
    job_id: str
    #: verified | unverified | failed | stopped | blocked
    status: str
    #: The tool result the lead reads: the gateway's evidence first, the
    #: worker's own words last and marked as unverified data.
    report: str
    #: Virtual paths under /mnt/user-data/outputs to present.
    artifacts: list[str] = field(default_factory=list)


@runtime_checkable
class CodeJobController(Protocol):
    def unavailable_reason(self) -> str | None:
        """None when coding jobs can run here, else why not (shown to the lead)."""
        ...

    async def run(self, *, thread_id: str, user_id: str, tool_call_id: str, brief: CodeJobBrief, turn: dict | None = None) -> CodeJobOutcome:
        """Run one job to its end (verified or not, stopped, blocked).

        `turn`: the calling turn's `messages` and run `context`, from which
        the gateway works out who led to the call (the person, or content
        read earlier: an app it registers is then a suggestion)."""
        ...


_controller: CodeJobController | None = None


def get_code_job_controller() -> CodeJobController | None:
    return _controller


def set_code_job_controller(controller: CodeJobController | None) -> None:
    global _controller
    _controller = controller


def reset_code_job_controller() -> None:
    set_code_job_controller(None)
