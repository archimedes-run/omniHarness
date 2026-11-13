"""Per-task research budget for the lead (spec 009 Slice 0, owner rule of
2026-11-13 after the real-model eval: research tasks made 40 to 80 calls)."""

from pydantic import BaseModel, Field


class ResearchBudgetConfig(BaseModel):
    """Caps on web lookups in one task (one person's turn and its resumes).

    A repeat of a fetch already made in the task is answered from the earlier
    result: it is not fetched again and does not count."""

    enabled: bool = Field(default=True, description="Whether the research budget applies")
    max_searches: int = Field(default=8, ge=1, description="web_search and image_search calls per task")
    max_fetches: int = Field(default=10, ge=1, description="web_fetch calls per task (distinct URLs)")
    answer_after_calls: int = Field(default=24, ge=1, description="After this many tool calls in a task, each result says to write the answer now")
