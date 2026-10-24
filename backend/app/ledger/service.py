"""The Project Ledger's rules (Feature 005, slice 2).

- A task's status is changed only by the user, or by a ledger_apply the policy
  layer let through (FR-013): confirmed, or since Feature 006 a routine task
  or note change at Tier 2. Nothing else calls `set_status`.
- Every change says who made it (FR-007): `user` from the UI,
  `assistant_confirmed` from a confirmed ledger_apply, `assistant_disclosed`
  from a Tier 2 one the reply disclosed, `assistant_granted` from one a
  standing grant let run in a scheduled run.
- A confirmed ledger_apply is validated in full before anything is written,
  then written in one transaction: all of it, or none of it.
- What the confirmation card lists is produced by `render`, from the same
  structured changes `apply` writes, so the card states exactly what will be
  stored (FR-010).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from omniharness.persistence.ledger import LedgerRepository


def _as_named(ref: Any, ref_names: dict[str, str]) -> str:
    """A project as the call named it: the name its create_project gave it
    (for an in-call ref), else the argument itself (a name or an id)."""
    key = str(ref)
    return ref_names.get(key, key)


PROJECT_STATUSES = ("active", "paused", "done", "archived")
TASK_STATUSES = ("todo", "doing", "blocked", "done", "dropped")
OWNER_KINDS = {"me": "user", "user": "user", "agent": "agent", "session": "session", "workflow": "workflow"}
OPS = ("create_project", "create_goal", "create_task", "update_task", "add_note", "link_thread")


class LedgerError(ValueError):
    """A change that cannot be applied, said in words the user can act on."""


class _DryRun(Exception):
    """Raised inside `validate`'s transaction so it rolls back: nothing written."""


def _norm(text: Any) -> str:
    """A title as matched: case, punctuation, quotes and spacing ignored."""
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "").lower()).split())


#: The shortest reference matched as a close title: "e" or "re" would match
#: almost anything.
_CLOSE_MIN = 3

#: A short id however it is written: "T-3", "t3", "T 3", "t - 3".
_SHORT_ID = re.compile(r"[Tt]\s*-?\s*(\d+)")

#: Where the policy layer pins what a change resolved to when it was proposed
#: (PolicyMiddleware, from `validate`'s resolutions): the task and project ids
#: apply must use, and the short id and stored names the card shows. Set only
#: by the server; a model's value is removed before a call runs or is stated.
PIN_KEY = "_pin"


def _close(key: str, title: str) -> bool:
    """A close title: every word of the (normalised) reference is a WHOLE word
    of the title, and the reference is at least _CLOSE_MIN characters. Never a
    raw substring ("e" is not "Ship release")."""
    if len(key.replace(" ", "")) < _CLOSE_MIN:
        return False
    words = set(title.split())
    return all(word in words for word in key.split())


def short_id_of(ref: Any) -> str | None:
    """ "T-<n>" when `ref` is a short id in any spelling, else None."""
    match = _SHORT_ID.fullmatch(str(ref or "").strip())
    return f"T-{int(match.group(1))}" if match else None


def strip_pins(changes: Any) -> Any:
    """`changes` without any PIN_KEY: what a model (or an edit) sent is never
    taken as a server pin."""
    if not isinstance(changes, list):
        return changes
    return [{k: v for k, v in c.items() if k != PIN_KEY} if isinstance(c, dict) else c for c in changes]


def _shapes_ok(changes: Any) -> None:
    if isinstance(changes, str):
        raise LedgerError("`changes` must be a list of change objects, not text")
    if not isinstance(changes, list) or not changes:
        raise LedgerError("there are no changes to apply")
    for change in changes:
        if not isinstance(change, dict) or change.get("op") not in OPS:
            raise LedgerError(f"unknown change {change!r}; ops are {', '.join(OPS)}")


class BatchError(LedgerError):
    """One card of an "Apply all" batch could not be applied; nothing was."""

    def __init__(self, index: int, reason: str):
        super().__init__(reason)
        self.index = index


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


def _shown(text: Any) -> str:
    from app.gateway.display_safe import safe_field

    return safe_field(text)


def render(changes: list[dict], *, stored: bool = True) -> list[str]:
    """One plain line per change: what the confirmation card lists.

    A project or goal created earlier in the same plan is named by its name,
    not by the plan-internal ref the model gave it ("p1"). A pinned update
    (PIN_KEY) names the task that will change by its short id and, with
    `stored`, its stored title and project (display-safe). `stored=False` is
    the model's copy of the plan: a plan stated to the model is the harness's
    own words (lineage.TRUSTED_TOOL_RESULTS), so it carries no stored text.
    """
    names: dict[str, str] = {}
    for c in changes or []:
        if isinstance(c, dict) and c.get("ref") and c.get("op") in ("create_project", "create_goal"):
            names[str(c["ref"])] = str(c.get("name") or c.get("title") or c["ref"])

    def name(ref: Any) -> str:
        return f"“{names[str(ref)]}”" if str(ref) in names else str(ref if ref is not None else "?")

    lines = []
    for c in changes or []:
        if isinstance(c, dict):
            c = {**c, **{k: name(c[k]) for k in ("project", "goal") if k in c}}
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
            goal = f", under goal {c['goal']}" if c.get("goal") else ""
            lines.append(f"Add task “{c.get('title', '')}” to {c.get('project', '?')}{goal}{due}{owner}")
        elif op == "update_task":
            fields = ", ".join(f"{k} → {c[k]}" for k in ("title", "status", "due_date", "owner") if k in c)
            pin = c.get(PIN_KEY) if isinstance(c.get(PIN_KEY), dict) else None
            if pin and pin.get("short_id"):
                # What will change, as resolved when it was proposed: the task's
                # short id and (with `stored`) its title and project as stored.
                if stored:
                    lines.append(f"Change task {pin['short_id']} “{_shown(pin.get('title'))}” in “{_shown(pin.get('project_name'))}”: {fields or 'nothing'}")
                else:
                    where = f" in {c['project']}" if c.get("project") not in (None, "") else ""
                    lines.append(f"Change task {pin['short_id']} (named {c.get('task', '?')}){where}: {fields or 'nothing'}")
                continue
            where = f" in {c['project']}" if c.get("project") not in (None, "") else ""
            lines.append(f"Change task {c.get('task', '?')}{where}: {fields or 'nothing'}")
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
        _shapes_ok(changes)
        with self.repo.transaction() as s:
            return self._apply_in(s, user_id=user_id, changes=changes, thread_id=thread_id, actor=actor, pending_action_id=pending_action_id)

    def validate(self, *, user_id: str, changes: list[dict], thread_id: str | None) -> list[dict]:
        """Check a plan the way `apply` would, WITHOUT writing anything.

        The whole plan is applied inside a transaction that is then rolled
        back, so every check `apply` makes (names that resolve, required
        fields, dates, statuses, in-plan refs) is made here, by the same code.
        Raises LedgerError when the plan could not be applied. Used before a
        plan is put on a confirmation card, so the user is never asked to
        approve a change that cannot happen (it would fail after they said
        yes). A plan that validates can still fail at apply if the ledger
        changes in between; apply checks again.

        Returns one resolution per change (what PIN_KEY carries): for an
        existing project, its id and stored name; for update_task, also the
        task's id, short id and stored title. Empty for a change that names
        nothing existing (a new project, an in-plan ref).
        """
        _shapes_ok(changes)
        resolutions: list[dict] = []
        try:
            with self.repo.transaction() as s:
                self._apply_in(s, user_id=user_id, changes=changes, thread_id=thread_id, actor="assistant_confirmed", pending_action_id=None, resolutions=resolutions)
                raise _DryRun
        except _DryRun:
            return resolutions

    def apply_batch(self, *, user_id: str, batches: list[tuple[list[dict], str | None]], actor: str, pending_action_id: str | None) -> list[list[str]]:
        """Apply several cards' changes ("Apply all") in ONE transaction: all
        of them or none. A card that cannot be applied raises BatchError
        naming it, and nothing at all is written."""
        out: list[list[str]] = []
        with self.repo.transaction() as s:
            for index, (changes, thread_id) in enumerate(batches):
                try:
                    out.append(self._apply_in(s, user_id=user_id, changes=changes, thread_id=thread_id, actor=actor, pending_action_id=pending_action_id))
                except LedgerError as exc:
                    raise BatchError(index, str(exc)) from exc
        return out

    def _apply_in(self, s, *, user_id: str, changes: list[dict], thread_id: str | None, actor: str, pending_action_id: str | None, resolutions: list[dict] | None = None) -> list[str]:
        _shapes_ok(changes)
        done: list[str] = []
        refs: dict[str, str] = {}
        goal_refs: dict[str, str] = {}
        # Rows this run created. They exist only in this transaction (and in
        # `validate`'s, which is rolled back), so they are never resolutions to
        # pin: a later change naming one resolves it by name at apply, in the
        # same transaction that creates it again.
        created: set[str] = set()
        # What each line calls a project: the name this call gave it, never
        # the name as stored. A ledger_apply result is trusted as the
        # harness's own words (lineage.TRUSTED_TOOL_RESULTS), so it carries
        # only the call's own arguments and ids; a stored name is whatever a
        # page or an email may have put there (review 5).
        ref_names: dict[str, str] = {}
        for c in changes:
            op = c["op"]
            stamp = {"owner_id": user_id, "actor": actor, "pending_action_id": pending_action_id}
            pin = c.get(PIN_KEY) if isinstance(c.get(PIN_KEY), dict) else {}
            resolved: dict = {}
            if resolutions is not None:
                resolutions.append(resolved)
            if op == "create_project":
                status = c.get("status") or "active"
                if status not in PROJECT_STATUSES:
                    raise LedgerError(f"project status {status!r} is not one of {', '.join(PROJECT_STATUSES)}")
                row = self.repo.create(s, "project", **stamp, name=_text(c, "name", limit=120, required=True), why=_text(c, "why", limit=2000), context=_text(c, "context", limit=8000), status=status)
                created.add(row["id"])
                if c.get("ref"):
                    refs[str(c["ref"])] = row["id"]
                    ref_names[str(c["ref"])] = row["name"]
                if thread_id:
                    # US1: the project links to the chat it was captured in.
                    self.repo.link(s, owner_id=user_id, actor=actor, from_kind="project", from_id=row["id"], to_kind="thread", to_ref=thread_id, label="The chat it was captured in")
                done.append(f"Created project “{row['name']}”.")
                continue
            task = None
            if pin.get("task_id") and op == "update_task":
                # Confirmed as resolved when proposed: exactly that task, or
                # nothing (never whatever the words match now).
                task = self._pinned_task(s, user_id, pin)
                project = self._pinned_project(s, user_id, task["project_id"])
                named = _as_named(c.get("project"), ref_names) if c.get("project") not in (None, "") else f"project {project['id']}"
            elif pin.get("project_id"):
                project = self._pinned_project(s, user_id, pin["project_id"])
                named = _as_named(c.get("project"), ref_names)
            elif op == "update_task" and c.get("project") in (None, ""):
                # A task named without its project: found by exact title (or
                # id) across the user's projects, only when exactly one matches.
                task = self._task_anywhere(s, user_id, c.get("task"))
                project = self._pinned_project(s, user_id, task["project_id"])
                named = f"project {project['id']}"
            else:
                project = self._project(s, user_id, c.get("project"), refs)
                named = _as_named(c.get("project"), ref_names)
            if project["id"] not in created:
                resolved.update({"project_id": project["id"], "project_name": project.get("name")})
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
                if c.get("ref"):
                    goal_refs[str(c["ref"])] = row["id"]
                done.append(f"Added goal “{row['title']}” to {named}.")
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
                    goal_id=self._goal(s, project, c["goal"], goal_refs, named) if c.get("goal") else None,
                    # Not the model's to set: it is not in the tool's
                    # contract and names paths evidence is matched on.
                    declared_files=[],
                )
                created.add(row["id"])
                if thread_id and c.get("todo_ref"):
                    self.repo.link(s, owner_id=user_id, actor=actor, from_kind="task", from_id=row["id"], to_kind="thread", to_ref=thread_id, todo_ref=str(c["todo_ref"])[:300])
                done.append(f"Added {row['short_id']} “{row['title']}” to {named}.")
            elif op == "update_task":
                if task is None:
                    task = self._task(s, project, c.get("task"), named)
                if task["id"] not in created:
                    resolved.update({"task_id": task["id"], "short_id": task["short_id"], "title": task["title"]})
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
                done.append(f"Updated {task['short_id']} in {named}.")
            elif op == "add_note":
                self.repo.create(s, "note", **stamp, project_id=project["id"], decided=_text(c, "decided", limit=4000, required=True), why=_text(c, "why", limit=4000), thread_id=thread_id)
                done.append(f"Recorded a decision in {named}.")
            elif op == "link_thread":
                if not thread_id:
                    raise LedgerError("link_thread: this conversation's id is not known here")
                self.repo.link(s, owner_id=user_id, actor=actor, from_kind="project", from_id=project["id"], to_kind="thread", to_ref=thread_id, label=_text(c, "label", limit=300))
                done.append(f"Attached this conversation to {named}.")
        return done

    # ---- undo: a write the assistant made without a confirmation -----------

    #: Who may have made a write that Undo reverts: the assistant at Tier 2
    #: (disclosed in its reply), under a standing grant, or a confirmed
    #: "Apply all" batch. Only changes carrying a "w-" write id are reachable,
    #: so a plan confirmed on its own card is not.
    UNDOABLE_ACTORS = ("assistant_disclosed", "assistant_granted", "assistant_confirmed")

    def undo_write(self, *, user_id: str, write_id: str) -> list[str]:
        """Revert every change one assistant write made, newest first, in one
        transaction. Refused, with nothing changed, when the write is not
        this user's, was already undone, or anything it touched has changed
        since (so Undo never overwrites a later edit)."""
        return self.undo_writes(user_id=user_id, write_ids=[write_id])

    def write_undone(self, *, user_id: str, write_id: str) -> bool:
        with self.repo.transaction() as s:
            return bool(self.repo.changes_caused_by(s, user_id, f"undo:{write_id}"))

    def undo_writes(self, *, user_id: str, write_ids: list[str]) -> list[str]:
        """Undo several writes together ("Undo all for this run"), newest
        first, ALL OR NOTHING in one transaction: if any one cannot be undone,
        none is."""
        from omniharness.persistence.ledger.sql import StaleWrite

        done: list[str] = []
        with self.repo.transaction() as s:
            for write_id in reversed(list(dict.fromkeys(write_ids))):
                if not isinstance(write_id, str) or not write_id.startswith("w-"):
                    raise LookupError(f"no write {write_id!r}")
                changes = self.repo.changes_caused_by(s, user_id, write_id)
                if not changes or any(c["actor"] not in self.UNDOABLE_ACTORS for c in changes):
                    raise LookupError(f"no write {write_id!r}")
                if self.repo.changes_caused_by(s, user_id, f"undo:{write_id}"):
                    raise LedgerError("this was already undone")
                try:
                    self._undo_in(s, user_id, write_id, changes, done)
                except StaleWrite as exc:
                    raise LedgerError("something it changed has been edited since, so it was not undone; change it back by hand") from exc
        return done

    def _undo_in(self, s, user_id: str, write_id: str, changes: list[dict], done: list[str]) -> None:
        stamp = {"owner_id": user_id, "actor": "user", "pending_action_id": f"undo:{write_id}"}
        # Per entity the write touched: what it was BEFORE the write (its
        # first change's `before`; None if the write created it) and what
        # the write LEFT (its last change's `after`). Only the latter is
        # checked against the row now, so an entity touched twice in one
        # write (or created and then updated) undoes cleanly, and a later
        # edit by anyone still refuses the whole undo.
        entities: dict[tuple[str, str], dict] = {}
        for change in changes:
            key = (change["entity"], change["entity_id"])
            slot = entities.setdefault(key, {"before": change["before"], "after": change["after"]})
            slot["after"] = change["after"]
        for (entity, entity_id), slot in reversed(list(entities.items())):
            before, after = slot["before"], slot["after"]
            version = (after or {}).get("version")
            if after is None:
                raise LedgerError(f"the {entity} it touched is gone")
            if before is None:  # it was created: remove it
                if not self.repo.remove(s, entity, entity_id, version=version, **stamp):
                    raise LedgerError(f"the {entity} it created is already gone")
                done.append(f"Removed the {entity} “{after.get('title') or after.get('decided') or after.get('name') or entity}”.")
            else:  # it was changed: put the fields back
                fields = {k: before[k] for k in after if k in before and before[k] != after[k] and k not in ("version", "updated_at", "created_at", "done_at")}
                if "due_date" in fields and isinstance(fields["due_date"], str):
                    fields["due_date"] = date.fromisoformat(fields["due_date"])
                if self.repo.update(s, entity, entity_id, version=version, **stamp, **fields) is None:
                    raise LedgerError(f"the {entity} it changed is gone")
                done.append(f"Put back {after.get('short_id') or entity} as it was.")

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
        if not matches:
            # The same name written differently ("test-p" for "TEST P"): case,
            # punctuation and spacing ignored. Never a partial name: a task
            # must not land in a project the user did not name.
            wanted = _norm(key)
            owned = s.scalars(select(LedgerProjectRow).where(LedgerProjectRow.owner_id == user_id)).all()
            matches = [row for row in owned if wanted and _norm(row.name) == wanted]
        if len(matches) == 1:
            return to_dict(matches[0])
        if len(matches) > 1:
            raise LedgerError(f"more than one project is called {key!r}; name it by id")
        raise LedgerError(f"there is no project {key!r}")

    @staticmethod
    def _goal(s, project: dict, ref: Any, goal_refs: dict[str, str], named: str) -> str:
        """A goal by in-plan ref, id, or exact title within the project."""
        from sqlalchemy import func, select

        from omniharness.persistence.ledger import LedgerGoalRow

        key = str(ref)
        if key in goal_refs:
            return goal_refs[key]
        row = s.get(LedgerGoalRow, key)
        if row is not None and row.project_id == project["id"]:
            return row.id
        matches = s.scalars(select(LedgerGoalRow).where(LedgerGoalRow.project_id == project["id"], func.lower(LedgerGoalRow.title) == key.lower())).all()
        if len(matches) == 1:
            return matches[0].id
        raise LedgerError(f"{named} has no goal {key!r}")

    @staticmethod
    def _task(s, project: dict, ref: Any, named: str) -> dict:
        """A task of `project`, as the call named it: its id or short id
        (T-3), its title (case, punctuation and spacing ignored), or a close
        title (part of it, or all of its words) when exactly one task matches.

        No guessing: a reference that matches more than one task, at the
        first level that matches anything, is refused, as is one that matches
        none. The error names candidates by short id only, never by their
        stored titles: a ledger_apply result is trusted as the harness's own
        words (lineage.TRUSTED_TOOL_RESULTS), and a stored title is whatever
        content may have put there (review 5).
        """
        from sqlalchemy import select

        from omniharness.persistence.ledger import LedgerTaskRow
        from omniharness.persistence.ledger.sql import to_dict

        key = str(ref or "").strip()
        if not key:
            raise LedgerError("update_task: name the task (its title or short id)")
        short = short_id_of(key)
        row = s.scalars(select(LedgerTaskRow).where(LedgerTaskRow.project_id == project["id"], (LedgerTaskRow.short_id == (short or key.upper())) | (LedgerTaskRow.id == key))).first()
        if row is not None:
            return to_dict(row)
        if short is not None:
            # A short id (in any spelling) that is not there is not a title to
            # guess from.
            raise LedgerError(f"{named} has no task {key!r}")
        tasks = s.scalars(select(LedgerTaskRow).where(LedgerTaskRow.project_id == project["id"]).order_by(LedgerTaskRow.created_at)).all()
        wanted = _norm(key)
        for matches in ([t for t in tasks if wanted and _norm(t.title) == wanted], [t for t in tasks if _close(wanted, _norm(t.title))]):
            if len(matches) == 1:
                return to_dict(matches[0])
            if len(matches) > 1:
                ids = ", ".join(t.short_id for t in matches[:10])
                raise LedgerError(f"the task {key!r} matches more than one task in {named} ({ids}); name it by its short id, or ask the user which one")
        raise LedgerError(f"{named} has no task {key!r}")

    @staticmethod
    def _pinned_project(s, user_id: str, project_id: str) -> dict:
        from omniharness.persistence.ledger import LedgerProjectRow
        from omniharness.persistence.ledger.sql import to_dict

        row = s.get(LedgerProjectRow, str(project_id))
        if row is None or row.owner_id != user_id:
            raise LedgerError("the project this was proposed for no longer exists")
        return to_dict(row)

    @staticmethod
    def _pinned_task(s, user_id: str, pin: dict) -> dict:
        """The task a confirmed change was proposed for, by its pinned id: it
        must still exist in one of the user's projects (and in the pinned
        project, when one was pinned)."""
        from omniharness.persistence.ledger import LedgerProjectRow, LedgerTaskRow
        from omniharness.persistence.ledger.sql import to_dict

        row = s.get(LedgerTaskRow, str(pin["task_id"]))
        project = s.get(LedgerProjectRow, row.project_id) if row is not None else None
        if row is None or project is None or project.owner_id != user_id or (pin.get("project_id") and row.project_id != pin["project_id"]):
            raise LedgerError(f"the task this was proposed for ({pin.get('short_id') or 'a task'}) no longer exists")
        return to_dict(row)

    @staticmethod
    def _task_anywhere(s, user_id: str, ref: Any) -> dict:
        """A task named WITHOUT its project: by id, or by exact title (case,
        punctuation and spacing ignored) when exactly one of the user's tasks
        has it. A close title or a short id is not enough here (every project
        has a T-1); the error says to name the project."""
        from sqlalchemy import select

        from omniharness.persistence.ledger import LedgerProjectRow, LedgerTaskRow
        from omniharness.persistence.ledger.sql import to_dict

        key = str(ref or "").strip()
        if not key:
            raise LedgerError("update_task: name the task (its title or short id) and its project")
        mine = select(LedgerTaskRow).join(LedgerProjectRow, LedgerTaskRow.project_id == LedgerProjectRow.id).where(LedgerProjectRow.owner_id == user_id)
        row = s.scalars(mine.where(LedgerTaskRow.id == key)).first()
        if row is not None:
            return to_dict(row)
        wanted = _norm(key)
        matches = [t for t in s.scalars(mine).all() if wanted and _norm(t.title) == wanted]
        if len(matches) == 1:
            return to_dict(matches[0])
        if len(matches) > 1:
            raise LedgerError(f"more than one task is called {key!r} across projects; name the project too, or ask the user which one")
        raise LedgerError(f"no task is called {key!r}; name its project too (a close title is matched within a named project)")

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
            dues = sorted(t["due_date"] for t in open_ if t["due_date"])
            # next_due: the earliest due date of an open task (Home shows it).
            out.append({**p, "open_tasks": len(open_), "overdue": len(overdue), "done_tasks": sum(1 for t in tasks if t["status"] == "done"), "next_due": dues[0] if dues else None})
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
