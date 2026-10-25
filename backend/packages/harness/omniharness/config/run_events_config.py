"""Run event storage configuration.

Controls where run events (messages + execution traces) are persisted.

Backends:
- auto (default): the gateway's SQL database (as `db`) when it has one,
  otherwise memory. The run journal is the chat's display history once a
  conversation is summarized; in memory it was lost on every gateway restart.
- memory: In-memory storage, data lost on restart. Suitable for
  development and testing.
- db: SQL database via SQLAlchemy ORM. Provides full query capability.
  Suitable for production deployments.
- jsonl: Append-only JSONL files. Lightweight alternative for
  single-node deployments that need persistence without a database.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RunEventsConfig(BaseModel):
    backend: Literal["auto", "memory", "db", "jsonl"] = Field(
        default="auto",
        description="Storage backend for run events. 'auto' (default): the SQL database when there is one, else memory. 'memory': no persistence. 'db': SQL. 'jsonl': single-node files.",
    )
    max_trace_content: int = Field(
        default=10240,
        description="Maximum trace content size in bytes before truncation (db backend only).",
    )
    track_token_usage: bool = Field(
        default=True,
        description="Whether RunJournal should accumulate token counts to RunRow.",
    )
