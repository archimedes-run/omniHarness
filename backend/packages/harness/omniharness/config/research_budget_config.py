"""Per-task research budget for the lead (spec 009 Slice 0, owner rule of
2026-11-13 after the real-model eval: research tasks made 40 to 80 calls)."""

from pydantic import BaseModel, Field


class ResearchBudgetConfig(BaseModel):
    """Caps on web lookups in one task (one person's turn and its resumes).

    A repeat of a web search or fetch already made in the task is answered
    from the earlier result: it is not made again and does not count. Only
    public web lookups are cached, never a private or local read."""

    enabled: bool = Field(default=True, description="Whether the research budget applies")
    max_searches: int = Field(default=8, ge=1, description="web_search and image_search calls per task")
    max_fetches: int = Field(default=10, ge=1, description="web_fetch calls per task (distinct URLs)")
    max_research: int = Field(default=3, ge=1, description="research (delegated web research) calls per task")
    answer_after_calls: int = Field(default=24, ge=1, description="After this many tool calls in a task, each result says to write the answer now")
    max_seconds: int = Field(default=150, ge=10, description="Research time per task: from 60% of it each result says to answer now; past it no more lookups are made")
    max_page_chars: int = Field(default=12000, ge=1000, description="A fetched page is shortened to this many characters for the model")
    subagent_max_searches: int = Field(default=5, ge=1, description="Searches per research subagent call")
    subagent_max_fetches: int = Field(default=5, ge=1, description="Fetches per research subagent call")
    subagent_max_seconds: int = Field(default=120, ge=10, description="Research time per research subagent call (below its 240 s limit)")

    def for_subagent(self) -> "ResearchBudgetConfig":
        """The research subagent's own, smaller budget: it returns what it has
        well before its time limit instead of failing at it."""
        return self.model_copy(
            update={
                "max_searches": min(self.max_searches, self.subagent_max_searches),
                "max_fetches": min(self.max_fetches, self.subagent_max_fetches),
                "max_research": 1,
                "max_seconds": min(self.max_seconds, self.subagent_max_seconds),
                "answer_after_calls": min(self.answer_after_calls, self.subagent_max_searches + self.subagent_max_fetches),
            }
        )
