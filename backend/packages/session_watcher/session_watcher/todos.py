"""What a session changed, applied only once a tool result confirms it.

Two things are tracked this way: the agent's own todo list (Claude TodoWrite,
TaskCreate, TaskUpdate; Codex update_plan) and the files it changed.

THE RULE (Feature 005 FR-031): a change is held as pending under its call id,
applied when the matching result succeeds, and discarded when it fails. A call
whose result never arrives is never applied. The reference implementation this
was ported from (sodiumsun/agenttrail, MIT; see THIRD-PARTY-NOTICES.md) applied
TodoWrite and update_plan lists at call time, so a failed or interrupted update
showed as the agent's plan.

Only titles and statuses are kept. Descriptions never reach this module: the
adapters drop them while parsing (FR-030).

The todo list is from session records only. Claude Code's on-disk task store
(~/.claude/tasks) is undocumented and is never read (FR-030a).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from .adapters.base import ToolCall, ToolResult

#: Calls awaiting a result, per session. The oldest is dropped (never applied)
#: past this, so a session that never reports results costs bounded memory.
MAX_PENDING = 64
#: Files remembered per session, newest kept.
MAX_FILES = 200
#: Statuses kept as written; anything else reads as "pending".
STATUSES = ("pending", "in_progress", "completed")


def _status(value: object) -> str:
    return value if isinstance(value, str) and value in STATUSES else "pending"


@dataclass
class ConfirmedActivity:
    """One session's confirmed todo list and changed files."""

    #: None until the agent first (successfully) writes a list.
    todos: list[tuple[str, str]] | None = None
    #: TaskCreate ids, so TaskUpdate can address an item: id -> index.
    _ids: dict[str, int] = field(default_factory=dict)
    _pending: OrderedDict[str, ToolCall] = field(default_factory=OrderedDict)
    files: list[str] = field(default_factory=list)

    def call(self, call: ToolCall) -> None:
        if call.todo is None and not call.files:
            return
        self._pending[call.call_id] = call
        while len(self._pending) > MAX_PENDING:
            self._pending.popitem(last=False)

    def result(self, result: ToolResult) -> None:
        call = self._pending.pop(result.call_id, None)
        if call is None or result.ok is not True:
            return  # failed, interrupted, unknown, or never a tracked call
        if call.todo is not None:
            self._apply(call.todo, result.created_id)
        self.add_files(call.files)

    def add_files(self, paths: tuple[str, ...] | list[str]) -> None:
        for path in paths:
            if path in self.files:
                self.files.remove(path)
            self.files.append(path)
        del self.files[:-MAX_FILES]

    def _apply(self, change: tuple, created_id: str | None) -> None:
        op = change[0]
        if op == "replace":
            self.todos = [(str(title), _status(status)) for title, status in change[1]]
            self._ids = {}
        elif op == "create":
            self.todos = list(self.todos or [])
            self.todos.append((str(change[1]), "pending"))
            if created_id:
                self._ids[created_id] = len(self.todos) - 1
        elif op == "update":
            index = self._ids.get(str(change[1]))
            if index is not None and self.todos is not None and index < len(self.todos):
                if change[2] == "deleted":
                    self.todos[index] = (self.todos[index][0], "deleted")
                else:
                    self.todos[index] = (self.todos[index][0], _status(change[2]))

    def visible_todos(self) -> list[tuple[str, str]] | None:
        if self.todos is None:
            return None
        return [t for t in self.todos if t[1] != "deleted"]
