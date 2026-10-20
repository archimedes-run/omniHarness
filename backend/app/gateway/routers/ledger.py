"""/api/ledger — the Project Ledger (Feature 005, slice 2; contracts/ledger-api.md).

The UI's direct edits come here, recorded as `actor=user` (FR-007, FR-014).
Edits carry the version they were based on and a stale one is refused with
409 and the current row, so two tabs never overwrite each other.

The ledger repository is synchronous (see omniharness/persistence/ledger/sql.py),
so every route runs its work in a worker thread, never on the event loop.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.ledger.service import PROJECT_STATUSES, TASK_STATUSES, LedgerError, LedgerService, _owner
from omniharness.persistence.ledger import StaleWrite

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


def _service(request: Request) -> LedgerService:
    service = getattr(request.app.state, "ledger_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="the project ledger needs a database (database.backend is memory)")
    return service


def _user(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if auth and auth.user:
        return str(auth.user.id)
    raise HTTPException(status_code=401, detail="Authentication required")


def _owned_project(service: LedgerService, user_id: str, project_id: str) -> dict:
    project = service.repo.project(project_id, user_id)
    if project is None:
        raise HTTPException(status_code=404, detail="no such project")
    return project


def _write(fn):
    """Run a write; map the ledger's errors to HTTP."""
    try:
        return fn()
    except StaleWrite as exc:
        raise HTTPException(status_code=409, detail={"message": "this changed since you opened it", "current": exc.current}) from exc
    except LedgerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---- bodies -------------------------------------------------------------------


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    why: str | None = Field(default=None, max_length=2000)
    context: str | None = Field(default=None, max_length=8000)


class ProjectPatch(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=120)
    why: str | None = Field(default=None, max_length=2000)
    context: str | None = Field(default=None, max_length=8000)
    status: Literal[PROJECT_STATUSES] | None = None  # type: ignore[valid-type]


class GoalIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    definition_of_done: str = Field(min_length=1, max_length=4000)
    target_date: date | None = None


class GoalPatch(BaseModel):
    version: int
    title: str | None = Field(default=None, min_length=1, max_length=200)
    definition_of_done: str | None = Field(default=None, min_length=1, max_length=4000)
    target_date: date | None = None


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_date: date | None = None
    owner: str | None = None
    goal_id: str | None = None


class TaskPatch(BaseModel):
    version: int
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: Literal[TASK_STATUSES] | None = None  # type: ignore[valid-type]
    due_date: date | None = None
    owner: str | None = None
    goal_id: str | None = None
    #: Explicit clears, since None means "unchanged" above.
    clear: list[Literal["due_date", "owner", "goal_id"]] = []


class NoteIn(BaseModel):
    decided: str = Field(min_length=1, max_length=4000)
    why: str | None = Field(default=None, max_length=4000)


class LinkIn(BaseModel):
    project_id: str
    to_kind: Literal["thread", "workflow", "session", "repository", "external"]
    to_ref: str = Field(min_length=1, max_length=512)
    label: str | None = Field(default=None, max_length=300)


class PromoteIn(BaseModel):
    thread_id: str = Field(min_length=1)
    project_id: str
    titles: list[str] = Field(min_length=1, max_length=50)


def _fields(body: BaseModel, *, exclude: set[str]) -> dict[str, Any]:
    return {k: v for k, v in body.model_dump(exclude=exclude, exclude_none=True).items()}


# ---- projects -------------------------------------------------------------------


@router.get("/projects")
@require_permission("threads", "read")
async def list_projects(request: Request) -> list[dict]:
    def work():
        return _service(request).summaries(user_id=_user(request), today=date.today())

    return await asyncio.to_thread(work)


@router.post("/projects", status_code=201)
@require_permission("threads", "write")
async def create_project(body: ProjectIn, request: Request) -> dict:
    def work():
        service, user = _service(request), _user(request)
        with service.repo.transaction() as s:
            return service.repo.create(s, "project", owner_id=user, actor="user", **_fields(body, exclude=set()))

    return await asyncio.to_thread(work)


@router.get("/projects/{project_id}")
@require_permission("threads", "read")
async def get_project(project_id: str, request: Request) -> dict:
    def work():
        view = _service(request).view(user_id=_user(request), project_id=project_id)
        if view is None:
            raise HTTPException(status_code=404, detail="no such project")
        return view

    return await asyncio.to_thread(work)


@router.patch("/projects/{project_id}")
@require_permission("threads", "write")
async def patch_project(project_id: str, body: ProjectPatch, request: Request) -> dict:
    def work():
        service, user = _service(request), _user(request)
        _owned_project(service, user, project_id)

        def write():
            with service.repo.transaction() as s:
                return service.repo.update(s, "project", project_id, owner_id=user, actor="user", version=body.version, **_fields(body, exclude={"version"}))

        return _write(write)

    return await asyncio.to_thread(work)


# ---- goals, tasks, notes ------------------------------------------------------------


@router.post("/projects/{project_id}/goals", status_code=201)
@require_permission("threads", "write")
async def create_goal(project_id: str, body: GoalIn, request: Request) -> dict:
    def work():
        service, user = _service(request), _user(request)
        _owned_project(service, user, project_id)
        with service.repo.transaction() as s:
            return service.repo.create(s, "goal", owner_id=user, actor="user", project_id=project_id, **_fields(body, exclude=set()))

    return await asyncio.to_thread(work)


@router.patch("/goals/{goal_id}")
@require_permission("threads", "write")
async def patch_goal(goal_id: str, body: GoalPatch, request: Request) -> dict:
    def work():
        service, user = _service(request), _user(request)
        goal = service.repo.get("goal", goal_id)
        if goal is None:
            raise HTTPException(status_code=404, detail="no such goal")
        _owned_project(service, user, goal["project_id"])

        def write():
            with service.repo.transaction() as s:
                return service.repo.update(s, "goal", goal_id, owner_id=user, actor="user", version=body.version, **_fields(body, exclude={"version"}))

        return _write(write)

    return await asyncio.to_thread(work)


@router.post("/projects/{project_id}/tasks", status_code=201)
@require_permission("threads", "write")
async def create_task(project_id: str, body: TaskIn, request: Request) -> dict:
    def work():
        service, user = _service(request), _user(request)
        _owned_project(service, user, project_id)

        def write():
            with service.repo.transaction() as s:
                return service.repo.create(s, "task", owner_id=user, actor="user", project_id=project_id, title=body.title, status="todo", due_date=body.due_date, owner=_owner(body.owner), goal_id=body.goal_id, declared_files=[])

        return _write(write)

    return await asyncio.to_thread(work)


@router.patch("/tasks/{task_id}")
@require_permission("threads", "write")
async def patch_task(task_id: str, body: TaskPatch, request: Request) -> dict:
    """The user's own edit, including status (FR-013: status changes here, or
    through a confirmed ledger_apply, and nowhere else)."""

    def work():
        service, user = _service(request), _user(request)
        task = service.repo.get("task", task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="no such task")
        _owned_project(service, user, task["project_id"])
        fields = _fields(body, exclude={"version", "clear"})
        if "owner" in fields:
            fields["owner"] = _owner(fields["owner"])
        for name in body.clear:
            fields[name] = None

        def write():
            with service.repo.transaction() as s:
                return service.repo.update(s, "task", task_id, owner_id=user, actor="user", version=body.version, **fields)

        return _write(write)

    return await asyncio.to_thread(work)


@router.post("/projects/{project_id}/notes", status_code=201)
@require_permission("threads", "write")
async def create_note(project_id: str, body: NoteIn, request: Request) -> dict:
    def work():
        service, user = _service(request), _user(request)
        _owned_project(service, user, project_id)
        with service.repo.transaction() as s:
            return service.repo.create(s, "note", owner_id=user, actor="user", project_id=project_id, **_fields(body, exclude=set()))

    return await asyncio.to_thread(work)


# ---- links and promotion ---------------------------------------------------------------


@router.post("/links", status_code=201)
@require_permission("threads", "write")
async def create_link(body: LinkIn, request: Request) -> dict:
    def work():
        service, user = _service(request), _user(request)
        _owned_project(service, user, body.project_id)
        with service.repo.transaction() as s:
            return service.repo.link(s, owner_id=user, actor="user", from_kind="project", from_id=body.project_id, to_kind=body.to_kind, to_ref=body.to_ref, label=body.label)

    return await asyncio.to_thread(work)


@router.delete("/links/{link_id}", status_code=204)
@require_permission("threads", "delete")
async def delete_link(link_id: str, request: Request) -> None:
    def work():
        service, user = _service(request), _user(request)
        link = service.repo.get("link", link_id)
        if link is None:
            raise HTTPException(status_code=404, detail="no such link")
        project_id = link["from_id"] if link["from_kind"] == "project" else (service.repo.get("task", link["from_id"]) or {}).get("project_id", "")
        _owned_project(service, user, project_id)
        with service.repo.transaction() as s:
            service.repo.unlink(s, link_id, owner_id=user, actor="user")

    return await asyncio.to_thread(work)


@router.get("/threads/{thread_id}/projects")
@require_permission("threads", "read", owner_check=True)
async def thread_projects(thread_id: str, request: Request) -> list[dict]:
    """The projects a conversation is attached to (FR-011)."""

    def work():
        service, user = _service(request), _user(request)
        out = []
        for link in service.repo.links_to("thread", thread_id):
            if link["from_kind"] != "project":
                continue
            project = service.repo.project(link["from_id"], user)
            if project is not None:
                out.append({"link_id": link["id"], "project": project})
        return out

    return await asyncio.to_thread(work)


@router.post("/tasks/promote", status_code=201)
@require_permission("threads", "write")
async def promote(body: PromoteIn, request: Request) -> list[dict]:
    """A thread's todo items become project tasks (FR-012). The thread is not touched."""

    def work():
        service, user = _service(request), _user(request)
        return _write(lambda: service.promote(user_id=user, project_id=body.project_id, thread_id=body.thread_id, titles=body.titles))

    return await asyncio.to_thread(work)


@router.post("/writes/{write_id}/undo")
@require_permission("threads", "write")
async def undo_write(write_id: str, request: Request) -> dict:
    """Undo, from a disclosure: revert a write the assistant made without a
    confirmation (a routine Tier 2 change, or one under a standing grant).
    Only the caller's own writes; refused with 409, changing nothing, when
    anything it touched has been edited since or it was already undone."""

    def work():
        service, user = _service(request), _user(request)
        try:
            return {"write_id": write_id, "undone": service.undo_write(user_id=user, write_id=write_id)}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="no such write") from exc
        except LedgerError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return await asyncio.to_thread(work)
