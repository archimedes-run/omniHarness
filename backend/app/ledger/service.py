"""The Project Ledger's rules (Feature 005, slice 2).

- A task's status is changed only by the user, or by a ledger_apply the user
  confirmed (FR-013). Nothing else calls `set_status`.
- Every change says who made it (FR-007): `user` from the UI,
  `assistant_confirmed` from a confirmed ledger_apply.
- A confirmed ledger_apply is validated in full before anything is written,
  then written in one transaction: all of it, or none of it.
- What the confirmation card lists is produced by `render`, from the same
  structured changes `apply` writes, so the card states exactly what will be
  stored (FR-010).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from omniharness.persistence.ledger import LedgerRepository

PROJECT_STATUSES = ("active", "paused", "done", "archived")
TASK_STATUSES = ("todo", "doing", "blocked", "done", "dropped")
OWNER_KINDS = {"me": "user", "user": "user", "agent": "agent", "session": "session", "workflow": "workflow"}
OPS = ("create_project", "create_goal", "create_task", "update_task", "add_note", "link_thread")


class LedgerError(ValueError):
    """A change that cannot be applied, said in words the user can act on."""


def _date(value: Any, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise LedgerError(f"{field} {value!r} is not a date (YYYY-MM-DD)") from exc


def _text(change: dict, field: str, *, limit: int, required: bool = False) -> str | None:
    value = change.get(field)
    if value in (None, ""):
        if required:
            raise LedgerError(f"{change.get('op')}: {field} is required")
        return None
    text = str(value).strip()
    if len(text) > limit:
        raise LedgerError(f"{change.get('op')}: {field} is longer than {limit} characters")
    return text


def _owner(value: Any) -> dict | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        kind = OWNER_KINDS.get(str(value.get("kind", "")))
        return {"kind": kind, "ref": value.get("ref")} if kind else None
    kind = OWNER_KINDS.get(str(value).lower())
    if kind is None:
        raise LedgerError(f"owner {value!r} is not one of me, agent, session, workflow")
    return {"kind": kind, "ref": None}


def render(changes: list[dict]) -> list[str]:
    """One plain line per change: what the confirmation card lists."""
    lines = []
    for c in changes or []:
        op = c.get("op") if isinstance(c, dict) else None
        if op == "create_project":
            why = f" — {c['why']}" if c.get("why") else ""
            lines.append(f"Create project “{c.get('name', '')}”{why}")
        elif op == "create_goal":
            due = f", target {c['target_date']}" if c.get("target_date") else ""
            lines.append(f"Add goal “{c.get('title', '')}” to {c.get('project', '?')}{due}: done when {c.get('definition_of_done', '')}")
        elif op == "create_task":
            due = f", due {c['due_date']}" if c.get("due_date") else ""
            owner = f", owner {c['owner']}" if c.get("owner") else ""
            lines.append(f"Add task “{c.get('title', '')}” to {c.get('project', '?')}{due}{owner}")
        elif op == "update_task":
            fields = ", ".join(f"{k} → {c[k]}" for k in ("title", "status", "due_date", "owner") if k in c)
            lines.append(f"Change task {c.get('task', '?')} in {c.get('project', '?')}: {fields or 'nothing'}")
        elif op == "add_note":
            why = f" (why: {c['why']})" if c.get("why") else ""
            lines.append(f"Record decision in {c.get('project', '?')}: {c.get('decided', '')}{why}")
        elif op == "link_thread":
            lines.append(f"Attach this conversation to {c.get('project', '?')}")
        else:
            lines.append(f"Unrecognised change: {c!r}")
    return lines


@dataclass
class LedgerService:
    repo: LedgerRepository

    # ---- chat: confirmed changes -------------------------------------------

    def apply(self, *, user_id: str, changes: list[dict], thread_id: str | None, actor: str = "assistant_confirmed", pending_action_id: str | None = None) -> list[str]:
        if not isinstance(changes, list) or not changes:
            raise LedgerError("there are no changes to apply")
        for change in changes:
            if not isinstance(change, dict) or change.get("op") not in OPS:
                raise LedgerError(f"unknown change {change!r}; ops are {', '.join(OPS)}")
        done: list[str] = []
        refs: dict[str, str] = {}
        with self.repo.transaction() as s:
            for c in changes:
                op = c["op"]
                stamp = {"owner_id": user_id, "actor": actor, "pending_action_id": pending_action_id}
                if op == "create_project":
                    status = c.get("status") or "active"
                    if status not in PROJECT_STATUSES:
                        raise LedgerError(f"project status {status!r} is not one of {', '.join(PROJECT_STATUSES)}")
                    row = self.repo.create(s, "project", **stamp, name=_text(c, "name", limit=120, required=True), why=_text(c, "why", limit=2000), context=_text(c, "context", limit=8000), status=status)
                    if c.get("ref"):
                        refs[str(c["ref"])] = row["id"]
                    done.append(f"Created project “{row['name']}”.")
                    continue
                project = self._project(s, user_id, c.get("project"), refs)
                if op == "create_goal":
                    row = self.repo.create(
                        s,
                        "goal",
                        **stamp,
                        project_id=project["id"],
                        title=_text(c, "title", limit=200, required=True),
                        definition_of_done=_text(c, "definition_of_done", limit=4000, required=True),
                        target_date=_date(c.get("target_date"), "target_date"),
                    )
                    done.append(f"Added goal “{row['title']}” to {project['name']}.")
                elif op == "create_task":
                    status = c.get("status") or "todo"
                    if status not in TASK_STATUSES:
                        raise LedgerError(f"task status {status!r} is not one of {', '.join(TASK_STATUSES)}")
                    row = self.repo.create(
                        s,
                        "task",
                        **stamp,
                        project_id=project["id"],
                        title=_text(c, "title", limit=300, required=True),
                        status=status,
                        due_date=_date(c.get("due_date"), "due_date"),
                        owner=_owner(c.get("owner")),
                        declared_files=list(c.get("declared_files") or []),
                    )
                    if thread_id and c.get("todo_ref"):
                        self.repo.link(s, owner_id=user_id, actor=actor, from_kind="task", from_id=row["id"], to_kind="thread", to_ref=thread_id, todo_ref=str(c["todo_ref"])[:300])
                    done.append(f"Added {row['short_id']} “{row['title']}” to {project['name']}.")
                elif op == "update_task":
                    task = self._task(s, project, c.get("task"))
                    fields: dict[str, Any] = {}
                    if "title" in c:
                        fields["title"] = _text(c, "title", limit=300, required=True)
                    if "status" in c:
                        if c["status"] not in TASK_STATUSES:
                            raise LedgerError(f"task status {c['status']!r} is not one of {', '.join(TASK_STATUSES)}")
                        fields["status"] = c["status"]
                    if "due_date" in c:
                        fields["due_date"] = _date(c.get("due_date"), "due_date")
                    if "owner" in c:
                        fields["owner"] = _owner(c.get("owner"))
                    self.repo.update(s, "task", task["id"], **stamp, version=None, **fields)
                    done.append(f"Updated {task['short_id']} in {project['name']}.")
                elif op == "add_note":
                    self.repo.create(s, "note", **stamp, project_id=project["id"], decided=_text(c, "decided", limit=4000, required=True), why=_text(c, "why", limit=4000), thread_id=thread_id)
                    done.append(f"Recorded a decision in {project['name']}.")
                elif op == "link_thread":
                    if not thread_id:
                        raise LedgerError("link_thread: this conversation's id is not known here")
                    self.repo.link(s, owner_id=user_id, actor=actor, from_kind="project", from_id=project["id"], to_kind="thread", to_ref=thread_id, label=_text(c, "label", limit=300))
                    done.append(f"Attached this conversation to {project['name']}.")
        return done

    def _project(self, s, user_id: str, ref: Any, refs: dict[str, str]) -> dict:
        from sqlalchemy import func, select

        from omniharness.persistence.ledger import LedgerProjectRow
        from omniharness.persistence.ledger.sql import to_dict

        if ref in (None, ""):
            raise LedgerError("a change names no project")
        key = str(ref)
        row = s.get(LedgerProjectRow, refs.get(key, key))
        if row is not None and row.owner_id == user_id:
            return to_dict(row)
        matches = s.scalars(select(LedgerProjectRow).where(LedgerProjectRow.owner_id == user_id, func.lower(LedgerProjectRow.name) == key.lower())).all()
        if len(matches) == 1:
            return to_dict(matches[0])
        if len(matches) > 1:
            raise LedgerError(f"more than one project is called {key!r}; name it by id")
        raise LedgerError(f"there is no project {key!r}")

    @staticmethod
    def _task(s, project: dict, ref: Any) -> dict:
        from sqlalchemy import select

        from omniharness.persistence.ledger import LedgerTaskRow
        from omniharness.persistence.ledger.sql import to_dict

        key = str(ref or "")
        row = s.scalars(select(LedgerTaskRow).where(LedgerTaskRow.project_id == project["id"], (LedgerTaskRow.short_id == key.upper()) | (LedgerTaskRow.id == key))).first()
        if row is None:
            raise LedgerError(f"{project['name']} has no task {key!r}")
        return to_dict(row)

    # ---- the UI: direct user edits ------------------------------------------

    def promote(self, *, user_id: str, project_id: str, thread_id: str, titles: list[str]) -> list[dict]:
        """Promote a thread's todo items to project tasks (FR-012).

        Each task links to its thread and names the todo it came from. The
        thread's own list is not touched: this reads nothing from it and
        writes nothing to it.
        """
        clean = [t.strip() for t in titles if isinstance(t, str) and t.strip()]
        if not clean:
            raise LedgerError("no todo items were chosen")
        if self.repo.project(project_id, user_id) is None:
            raise LedgerError("there is no such project")
        created = []
        with self.repo.transaction() as s:
            for title in clean:
                task = self.repo.create(s, "task", owner_id=user_id, actor="user", project_id=project_id, title=title[:300], status="todo", declared_files=[])
                self.repo.link(s, owner_id=user_id, actor="user", from_kind="task", from_id=task["id"], to_kind="thread", to_ref=thread_id, todo_ref=title[:300])
                created.append(task)
            self.repo.link(s, owner_id=user_id, actor="user", from_kind="project", from_id=project_id, to_kind="thread", to_ref=thread_id)
        return created

    # ---- reading ---------------------------------------------------------------

    def view(self, *, user_id: str, project_id: str) -> dict | None:
        project = self.repo.project(project_id, user_id)
        if project is None:
            return None
        tasks = self.repo.children("task", project_id)
        goals = self.repo.children("goal", project_id)
        for goal in goals:
            mine = [t for t in tasks if t["goal_id"] == goal["id"] and t["status"] != "dropped"]
            goal["progress"] = {"done": sum(1 for t in mine if t["status"] == "done"), "total": len(mine)}
        return {
            "project": project,
            "goals": goals,
            "tasks": tasks,
            "notes": self.repo.children("note", project_id),
            "links": self.repo.links_from("project", project_id),
        }

    def summaries(self, *, user_id: str, today: date) -> list[dict]:
        out = []
        for p in self.repo.projects(user_id):
            tasks = self.repo.children("task", p["id"])
            open_ = [t for t in tasks if t["status"] not in ("done", "dropped")]
            overdue = [t for t in open_ if t["due_date"] and date.fromisoformat(t["due_date"]) < today]
            out.append({**p, "open_tasks": len(open_), "overdue": len(overdue), "done_tasks": sum(1 for t in tasks if t["status"] == "done")})
        return out

    def read_text(self, *, user_id: str, project: str | None, today: date) -> str:
        """The ledger as the model reads it (ledger_read)."""
        projects = self.repo.projects(user_id)
        if not projects:
            return "The ledger has no projects yet."
        if project is None:
            lines = ["Projects:"]
            for p in self.summaries(user_id=user_id, today=today):
                lines.append(f"- {p['name']} ({p['status']}, id {p['id']}): {p['open_tasks']} open task(s), {p['overdue']} overdue")
            return "\n".join(lines)
        key = project.lower()
        match = next((p for p in projects if p["id"] == project or p["name"].lower() == key), None)
        if match is None:
            return f"There is no project {project!r}."
        v = self.view(user_id=user_id, project_id=match["id"]) or {}
        lines = [f"{match['name']} ({match['status']})" + (f": {match['why']}" if match.get("why") else "")]
        if match.get("context"):
            lines.append(f"Context: {match['context']}")
        for g in v.get("goals", []):
            lines.append(f"Goal: {g['title']} ({g['progress']['done']}/{g['progress']['total']} done)" + (f", target {g['target_date']}" if g["target_date"] else ""))
        for t in v.get("tasks", []):
            owner = f", owner {t['owner']['kind']}" if t.get("owner") else ""
            due = f", due {t['due_date']}" if t["due_date"] else ""
            lines.append(f"{t['short_id']} [{t['status']}] {t['title']}{due}{owner}")
        for n in v.get("notes", []):
            lines.append(f"Decision: {n['decided']}" + (f" (why: {n['why']})" if n.get("why") else ""))
        return "\n".join(lines)
