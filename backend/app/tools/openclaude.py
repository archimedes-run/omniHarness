"""OpenClaude coding tool — wraps the openclaude CLI for agent-driven coding tasks.

Installation prerequisite (add to the gateway Dockerfile):
    RUN npm install -g @gitlawb/openclaude
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from typing import Any, Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)


class _Input(BaseModel):
    prompt: str


class OpenClaudeCodingTool(BaseTool):
    """Delegates a coding task to openclaude (a Claude Code community fork).

    Set ``CLAUDE_CODE_USE_OPENAI=1`` to route to an OpenAI-compatible backend.
    ``NO_COLOR`` / ``FORCE_COLOR`` env vars are set but may be unreliable upstream;
    ``_strip_ansi`` is the authoritative ANSI cleaner on the output.

    Requires ``openclaude`` available on PATH in the gateway container:
        npm install -g @gitlawb/openclaude
    """

    name: str = "openclaude_coder"
    description: str = (
        "Delegate a coding task to OpenClaude, an AI coding agent. "
        "Provide a clear, self-contained prompt describing exactly what to implement or fix."
    )
    args_schema: type[BaseModel] = _Input
    timeout_seconds: int = Field(default=300)

    def _run(self, prompt: str, run_manager: Optional[Any] = None) -> str:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self._arun(prompt))

    async def _arun(self, prompt: str, run_manager: Optional[Any] = None) -> str:
        cmd = f"CLAUDE_CODE_USE_OPENAI=1 NO_COLOR=1 FORCE_COLOR=0 openclaude {shlex.quote(prompt)}"
        logger.debug("openclaude invocation: %s", cmd)
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
            if stderr:
                err = stderr.decode(errors="replace").strip()
                if err:
                    logger.warning("openclaude stderr: %s", err)
            return _strip_ansi(stdout.decode(errors="replace")).strip()
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return f"Error: OpenClaude execution timed out after {self.timeout_seconds} seconds."
        except FileNotFoundError:
            return "Error: openclaude is not installed. Run: npm install -g @gitlawb/openclaude"
        except Exception as exc:
            logger.exception("openclaude execution failed")
            return f"Error: {exc}"


# Module-level instance referenced by config.yaml:
#   tools:
#     - name: openclaude_coder
#       use: app.tools.openclaude:openclaude_coder
openclaude_coder = OpenClaudeCodingTool()
