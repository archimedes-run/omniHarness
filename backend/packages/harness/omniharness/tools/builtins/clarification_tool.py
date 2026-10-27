from typing import Literal

from langchain.tools import tool

#: The question kinds the tool accepts (spec 009 FR-057). Choosing between
#: approaches, confirming a risky action and asking approval for a suggestion
#: are not questions for the person: the agent picks a sensible default, and
#: consequential actions are stopped by the policy layer's confirmation cards
#: (constitution Article II), never by a model-written "are you sure?".
CLARIFICATION_TYPES = ("missing_info", "ambiguous_requirement")


@tool("ask_clarification", parse_docstring=True, return_direct=True)
def ask_clarification_tool(
    question: str,
    clarification_type: Literal["missing_info", "ambiguous_requirement"],
    context: str | None = None,
    options: list[str] | None = None,
) -> str:
    """Ask the person one question when information the task cannot go ahead without is missing, and no read tool (memory, files, ledger, mail, calendar, web) can find it.

    Ask before you start working, not halfway through.

    Do not use this tool to:
    - confirm a risky or consequential action (the system shows the person a confirmation card for those automatically);
    - let the person choose between approaches (pick a sensible default and state it);
    - ask permission to read anything (reading never needs permission).

    The run pauses until the person answers.

    Args:
        question: The one question to ask. Be specific.
        clarification_type: missing_info (a required value is absent) or ambiguous_requirement (the request has two readings that lead to different results and nothing you can read settles it).
        context: Optional: why the task cannot go ahead without the answer.
        options: Optional: only for a missing value with a known small set (for example which of two calendars). Never a menu of approaches.
    """
    # This is a placeholder implementation
    # The actual logic is handled by ClarificationMiddleware which intercepts this tool call
    # and interrupts execution to present the question to the user
    return "Clarification request processed by middleware"
