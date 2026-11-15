"""The Artifact store (Spec 012, Slice 1): records and immutable versions over the
shared SQL store, content in the blob store. SYNCHRONOUS, like the ledger: the
chat tools call it from a tool invocation; the HTTP routes run it in the
threadpool.

Rules every write here keeps, whatever path called it:

* OWNER SCOPED. Every read and write names the owner; another owner's id is
  "not found", exactly like an id that does not exist.
* NEVER OVERWRITE (FR-002). A version row is inserted once and never updated.
  A change, a restore and an owner edit are each a new version carrying the
  version it was based on; a stale base is refused with the current number and
  nothing is written (FR-006, FR-010).
* CAPS BEFORE STORAGE (FR-004). Size caps are checked by `kinds`, the owner
  quota here, both before a blob is written or a row is inserted.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.gateway.artifacts_store import blobs, caps
from app.gateway.artifacts_store.kinds import CODE_KINDS, SEARCH_KINDS, Canonical
from app.gateway.display_safe import model_line
from omniharness.persistence.artifacts.model import ArtifactBuildRow, ArtifactBundleFileRow, ArtifactCheckRow, ArtifactCodeRow, ArtifactImportRow, ArtifactPageRow, ArtifactRow, ArtifactVersionRow

logger = logging.getLogger(__name__)

ORIGINS = ("tool", "owner_edit", "restore", "import", "duplicate")
#: user: the owner's own turn or click; content: made after outside content
#: was read; import: a file a chat produced, indexed from its outputs.
LINEAGES = ("user", "content", "import")


class StoreError(Exception):
    code = "invalid_request"
    status = 422

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra


class NotFound(StoreError):
    code, status = "artifact_not_found", 404


class VersionNotFound(StoreError):
    code, status = "version_not_found", 404


class Stale(StoreError):
    code, status = "stale_base_version", 409


class Archived(StoreError):
    code, status = "artifact_archived", 409


class NotArchived(StoreError):
    code, status = "not_archived", 409


class Mismatch(StoreError):
    code, status = "confirmation_mismatch", 400


class QuotaExceeded(StoreError):
    code, status = "quota_exceeded", 413


class InvalidRequest(StoreError):
    code, status = "invalid_request", 422


class NotEditable(StoreError):
    code, status = "not_editable", 422


class FixRefused(StoreError):
    """The one automatic fix (FR-018): refused for a version whose checks did
    not fail, a version that is itself a fix, or one already fixed."""

    code, status = "fix_refused", 409


class BuildBusy(StoreError):
    code, status = "build_running", 409


#: Code version states (FR-002) and check states (FR-018).
BUILD_STATES = ("ok", "build_failed")
CHECK_STATES = ("pending", "passed", "failed", "not_checked")
#: A running check or build whose worker has not beaten for this long is stale.
LIVENESS_SECONDS = 90.0


def new_id() -> str:
    """Random, URL-safe, 22 characters (128 bits)."""
    return secrets.token_urlsafe(16)


def iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat() if ts is not None else None


def clean_title(value: Any) -> str:
    title = model_line(value)[: caps.TITLE_CHARS].strip()
    if not title:
        raise InvalidRequest("A title is required (1 to 120 characters).")
    return title


def clean_note(value: Any) -> str | None:
    if value is None:
        return None
    note = model_line(value)[: caps.NOTE_CHARS].strip()
    return note or None


def _version_dict(row: ArtifactVersionRow, kind: str | None = None) -> dict:
    from app.gateway.artifacts_store.kinds import render_of

    return {
        "render": render_of(kind, row.media_type, row.stored) if kind else None,
        "n": row.n,
        "content_hash": row.content_hash,
        "size": row.size,
        "media_type": row.media_type,
        "language": row.language,
        "lineage": row.lineage,
        "lineage_source": row.lineage_source,
        "origin": row.origin,
        "base_version": row.base_version,
        "note": row.note,
        "thread_id": row.thread_id,
        "turn_id": row.turn_id,
        "tool_call_id": row.tool_call_id,
        "stored": row.stored,
        "created_at": iso(row.created_at),
    }


def _loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


def check_dict(row: ArtifactCheckRow | None, now: float | None = None) -> dict:
    """A version's checks for the API. A pending check whose worker stopped
    beating reads `not_checked` (fail closed: never shown as checked)."""
    if row is None:
        return {"state": "not_checked", "summary": ["the checks did not run"], "failures": [], "warnings": [], "shots": {"light": False, "dark": False}, "checked_at": None}
    result = _loads(row.result, {})
    state = row.state
    summary = result.get("summary") or []
    if state == "pending" and (now or time.time()) - (row.heartbeat_at or row.updated_at) > LIVENESS_SECONDS:
        state, summary = "not_checked", ["the checks stopped before they finished"]
    return {
        "state": state,
        "summary": summary[:8],
        "failures": (result.get("failures") or [])[:14],
        "warnings": (result.get("warnings") or [])[:5],
        "widths": result.get("widths") or [],
        "themes": result.get("themes") or [],
        "shots": {"light": bool(row.shot_light), "dark": bool(row.shot_dark)},
        "checked_at": iso(row.updated_at) if state != "pending" else None,
    }


def code_dict(code: ArtifactCodeRow | None, check: ArtifactCheckRow | None) -> dict | None:
    if code is None:
        return None
    return {
        "build_state": code.build_state,
        "has_source": code.source_hash is not None,
        "findings": _loads(code.findings, []),
        "fix_of": code.fix_of,
        "recipe": _loads(code.recipe, None),
        "check": check_dict(check) if code.build_state == "ok" else None,
    }


class ArtifactStore:
    def __init__(self, engine: Engine) -> None:
        self._sf = sessionmaker(engine, expire_on_commit=False)
        # One write at a time in this process; across workers the unique
        # (artifact_id, n) constraint refuses the second of two racing writes.
        self._write_lock = threading.Lock()

    @contextmanager
    def _write(self) -> Iterator[Session]:
        with self._write_lock, self._sf() as session, session.begin():
            yield session

    @contextmanager
    def _read(self) -> Iterator[Session]:
        with self._sf() as session:
            yield session

    # -- loading -------------------------------------------------------------------------

    @staticmethod
    def _artifact(s: Session, owner_id: str, artifact_id: str) -> ArtifactRow:
        if not isinstance(artifact_id, str) or not artifact_id:
            raise NotFound("No such artifact.")
        row = s.execute(select(ArtifactRow).where(ArtifactRow.id == artifact_id, ArtifactRow.owner_id == owner_id)).scalar_one_or_none()
        if row is None:
            raise NotFound("No such artifact.")
        return row

    @staticmethod
    def _version(s: Session, owner_id: str, artifact_id: str, n: int) -> ArtifactVersionRow:
        row = s.execute(select(ArtifactVersionRow).where(ArtifactVersionRow.artifact_id == artifact_id, ArtifactVersionRow.owner_id == owner_id, ArtifactVersionRow.n == n)).scalar_one_or_none()
        if row is None:
            raise VersionNotFound(f"This artifact has no version {n}.")
        return row

    def _summary(self, s: Session, row: ArtifactRow) -> dict:
        latest = s.execute(select(ArtifactVersionRow).where(ArtifactVersionRow.artifact_id == row.id, ArtifactVersionRow.n == row.latest_version)).scalar_one_or_none()
        count = s.execute(select(func.count()).select_from(ArtifactVersionRow).where(ArtifactVersionRow.artifact_id == row.id)).scalar_one()
        return {
            "id": row.id,
            "kind": row.kind,
            "title": row.title,
            "latest_version": row.latest_version,
            "version_count": int(count),
            "pinned": bool(row.pinned),
            "saved": bool(row.saved),
            "saved_at": iso(row.saved_at),
            "origin_deleted": bool(row.origin_deleted),
            "archived": row.archived_at is not None,
            "archived_at": iso(row.archived_at),
            "origin_thread_id": row.origin_thread_id,
            "origin_turn_id": row.origin_turn_id,
            "imported_from": row.imported_from,
            "lineage": latest.lineage if latest else None,
            "lineage_source": latest.lineage_source if latest else None,
            "language": latest.language if latest else None,
            "media_type": latest.media_type if latest else None,
            "size": latest.size if latest else None,
            "created_at": iso(row.created_at),
            "updated_at": iso(row.updated_at),
            **({"code": self._code_summary(s, row)} if row.kind in CODE_KINDS else {}),
        }

    @staticmethod
    def _code_rows(s: Session, artifact_id: str, n: int) -> tuple[ArtifactCodeRow | None, ArtifactCheckRow | None]:
        code = s.execute(select(ArtifactCodeRow).where(ArtifactCodeRow.artifact_id == artifact_id, ArtifactCodeRow.n == n)).scalar_one_or_none()
        check = s.execute(select(ArtifactCheckRow).where(ArtifactCheckRow.artifact_id == artifact_id, ArtifactCheckRow.n == n)).scalar_one_or_none()
        return code, check

    def _code_summary(self, s: Session, row: ArtifactRow) -> dict:
        """The latest version's build and check state, and the version to SHOW:
        the newest one that built (a failed build keeps the last good one shown)."""
        code, check = self._code_rows(s, row.id, row.latest_version)
        shown = s.execute(select(func.max(ArtifactCodeRow.n)).where(ArtifactCodeRow.artifact_id == row.id, ArtifactCodeRow.build_state == "ok")).scalar_one_or_none()
        build = s.execute(select(ArtifactBuildRow).where(ArtifactBuildRow.artifact_id == row.id)).scalar_one_or_none()
        return {
            "build_state": code.build_state if code else None,
            "check_state": check_dict(check)["state"] if code and code.build_state == "ok" else None,
            "shown_version": shown,
            "build": self._build_dict(build),
        }

    @staticmethod
    def _build_dict(build: ArtifactBuildRow | None) -> dict | None:
        if build is None:
            return None
        state = build.state
        if state == "running" and time.time() - build.heartbeat_at > LIVENESS_SECONDS:
            state = "interrupted"
        return {"state": state, "base_version": build.base_version, "reason": build.reason, "result_version": build.result_version, "started_at": iso(build.started_at)}

    def _vdict(self, s: Session, kind: str, v: ArtifactVersionRow) -> dict:
        out = _version_dict(v, kind)
        if kind in CODE_KINDS:
            out["code"] = code_dict(*self._code_rows(s, v.artifact_id, v.n))
        return out

    # -- reads ---------------------------------------------------------------------------

    def get(self, owner_id: str, artifact_id: str) -> dict:
        with self._read() as s:
            return self._summary(s, self._artifact(s, owner_id, artifact_id))

    def detail(self, owner_id: str, artifact_id: str) -> dict:
        with self._read() as s:
            row = self._artifact(s, owner_id, artifact_id)
            return {**self._summary(s, row), "versions": self._versions(s, row)}

    def _versions(self, s: Session, row: ArtifactRow) -> list[dict]:
        rows = s.execute(select(ArtifactVersionRow).where(ArtifactVersionRow.artifact_id == row.id).order_by(ArtifactVersionRow.n.desc())).scalars().all()
        return [self._vdict(s, row.kind, v) for v in rows]

    def versions(self, owner_id: str, artifact_id: str) -> list[dict]:
        with self._read() as s:
            return self._versions(s, self._artifact(s, owner_id, artifact_id))

    def version(self, owner_id: str, artifact_id: str, n: int) -> tuple[dict, dict, ArtifactVersionRow]:
        """(summary, version dict, the row) for one version."""
        with self._read() as s:
            row = self._artifact(s, owner_id, artifact_id)
            v = self._version(s, owner_id, artifact_id, n)
            return self._summary(s, row), self._vdict(s, row.kind, v), v

    def content(self, owner_id: str, version: ArtifactVersionRow) -> bytes:
        return blobs.read(owner_id, version.content_hash)

    def list(
        self, owner_id: str, *, saved: str = "all", kind: str | None = None, pinned: bool | None = None, archived: str = "false", thread: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict], int]:
        where = [ArtifactRow.owner_id == owner_id]
        if saved == "true":
            where.append(ArtifactRow.saved.is_(True))
        elif saved == "false":
            where.append(ArtifactRow.saved.is_(False))
        if kind:
            where.append(ArtifactRow.kind == kind)
        if pinned is not None:
            where.append(ArtifactRow.pinned.is_(pinned))
        if archived == "false":
            where.append(ArtifactRow.archived_at.is_(None))
        elif archived == "true":
            where.append(ArtifactRow.archived_at.is_not(None))
        if thread:
            where.append(ArtifactRow.origin_thread_id == thread)
        if q:
            pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append(or_(ArtifactRow.title.ilike(pattern, escape="\\"), ArtifactRow.search_text.ilike(pattern, escape="\\")))
        with self._read() as s:
            total = s.execute(select(func.count()).select_from(ArtifactRow).where(*where)).scalar_one()
            rows = s.execute(select(ArtifactRow).where(*where).order_by(ArtifactRow.pinned.desc(), ArtifactRow.updated_at.desc(), ArtifactRow.id).limit(limit).offset(offset)).scalars().all()
            return [self._summary(s, r) for r in rows], int(total)

    def thread_artifacts(self, owner_id: str, thread_id: str) -> list[dict]:
        """Artifacts with a version made in (or imported from) this thread, and those versions."""
        with self._read() as s:
            versions = s.execute(select(ArtifactVersionRow).where(ArtifactVersionRow.owner_id == owner_id, ArtifactVersionRow.thread_id == thread_id).order_by(ArtifactVersionRow.created_at, ArtifactVersionRow.n)).scalars().all()
            by_artifact: dict[str, list[dict]] = {}
            for v in versions:
                by_artifact.setdefault(v.artifact_id, []).append({"n": v.n, "turn_id": v.turn_id, "tool_call_id": v.tool_call_id, "origin": v.origin, "created_at": iso(v.created_at)})
            out = []
            for artifact_id, items in by_artifact.items():
                row = s.execute(select(ArtifactRow).where(ArtifactRow.id == artifact_id, ArtifactRow.owner_id == owner_id)).scalar_one_or_none()
                if row is not None:
                    out.append({**self._summary(s, row), "versions_in_thread": items})
            out.sort(key=lambda a: a["created_at"] or "")
            return out

    def usage(self, owner_id: str) -> int:
        with self._read() as s:
            return self._usage(s, owner_id)

    @staticmethod
    def _usage(s: Session, owner_id: str) -> int:
        """Bytes of distinct blobs: versions' content and webapp bundle files."""
        versions = select(ArtifactVersionRow.content_hash.label("h"), ArtifactVersionRow.size.label("size")).where(ArtifactVersionRow.owner_id == owner_id, ArtifactVersionRow.stored == "blob")
        files = select(ArtifactBundleFileRow.content_hash.label("h"), ArtifactBundleFileRow.size.label("size")).where(ArtifactBundleFileRow.owner_id == owner_id)
        sources = select(ArtifactCodeRow.source_hash.label("h"), ArtifactCodeRow.source_size.label("size")).where(ArtifactCodeRow.owner_id == owner_id, ArtifactCodeRow.source_hash.is_not(None))
        pages = select(ArtifactPageRow.content_hash.label("h"), ArtifactPageRow.size.label("size")).where(ArtifactPageRow.owner_id == owner_id, ArtifactPageRow.content_hash.is_not(None))
        both = versions.union_all(files, sources, pages).subquery()
        sized = select(both.c.h, func.max(both.c.size).label("size")).group_by(both.c.h).subquery()
        return int(s.execute(select(func.coalesce(func.sum(sized.c.size), 0))).scalar_one())

    @staticmethod
    def _refs(s: Session, owner_id: str, content_hash: str) -> int:
        """How many stored things of this owner use this blob."""
        versions = s.execute(select(func.count()).select_from(ArtifactVersionRow).where(ArtifactVersionRow.owner_id == owner_id, ArtifactVersionRow.content_hash == content_hash, ArtifactVersionRow.stored == "blob")).scalar_one()
        files = s.execute(select(func.count()).select_from(ArtifactBundleFileRow).where(ArtifactBundleFileRow.owner_id == owner_id, ArtifactBundleFileRow.content_hash == content_hash)).scalar_one()
        sources = s.execute(select(func.count()).select_from(ArtifactCodeRow).where(ArtifactCodeRow.owner_id == owner_id, ArtifactCodeRow.source_hash == content_hash)).scalar_one()
        shots = s.execute(select(func.count()).select_from(ArtifactCheckRow).where(ArtifactCheckRow.owner_id == owner_id, or_(ArtifactCheckRow.shot_light == content_hash, ArtifactCheckRow.shot_dark == content_hash))).scalar_one()
        pages = s.execute(select(func.count()).select_from(ArtifactPageRow).where(ArtifactPageRow.owner_id == owner_id, ArtifactPageRow.content_hash == content_hash)).scalar_one()
        return int(versions) + int(files) + int(sources) + int(shots) + int(pages)

    # -- writes --------------------------------------------------------------------------

    def _store_blob(self, s: Session, owner_id: str, data: bytes) -> tuple[str, bool]:
        """Quota check, then the blob (written before the row commits; made
        sure of again after it commits, see _settle). Returns (hash, newly written)."""
        content_hash = blobs.sha256(data)
        known = self._refs(s, owner_id, content_hash)
        if not known:
            used = self._usage(s, owner_id)
            if used + len(data) > caps.OWNER_BYTES:
                raise QuotaExceeded("Your artifact store is full.", used=used, cap=caps.OWNER_BYTES, size=len(data))
        existed = blobs.path_for(owner_id, content_hash).exists()
        blobs.write(owner_id, data)
        return content_hash, not existed

    def _insert_version(
        self,
        s: Session,
        row: ArtifactRow,
        canon: Canonical | None,
        *,
        n: int,
        base_version: int | None,
        lineage: str,
        lineage_source: str | None,
        origin: str,
        note: str | None,
        thread_id: str | None,
        turn_id: str | None,
        tool_call_id: str | None,
        chat_ref: tuple[str, int, str] | None = None,
        post: dict | None = None,
        code: dict | None = None,
    ) -> ArtifactVersionRow:
        if lineage not in LINEAGES or origin not in ORIGINS:
            raise InvalidRequest("Bad lineage or origin.")
        if chat_ref is not None:
            content_hash, size, chat_path = chat_ref
            media_type, language, stored = "application/octet-stream", None, "chat"
        else:
            assert canon is not None
            content_hash, _ = self._store_blob(s, row.owner_id, canon.data)
            if post is not None:
                post["ensure"][content_hash] = canon.data
            size, media_type, language, stored, chat_path = len(canon.data), canon.media_type, canon.language, "blob", None
        version = ArtifactVersionRow(
            artifact_id=row.id,
            owner_id=row.owner_id,
            n=n,
            content_hash=content_hash,
            size=size,
            media_type=media_type,
            language=language,
            lineage=lineage,
            lineage_source=(model_line(lineage_source)[:200] or None) if lineage_source else None,
            origin=origin,
            base_version=base_version,
            note=clean_note(note),
            thread_id=thread_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            stored=stored,
            chat_path=chat_path,
            created_at=time.time(),
        )
        s.add(version)
        row.latest_version = n
        row.updated_at = version.created_at
        if canon is not None and row.kind in SEARCH_KINDS and canon.search_text is not None:
            row.search_text = canon.search_text[: caps.SEARCH_TEXT_CHARS]
        s.flush()
        if row.kind in CODE_KINDS:
            self._insert_code(s, row, version, canon, code or {}, post)
        return version

    def _insert_code(self, s: Session, row: ArtifactRow, version: ArtifactVersionRow, canon: Canonical | None, code: dict, post: dict | None) -> None:
        """The code row of a new html/react version, in the same transaction,
        and its checks row (`pending`; the checks fill it). `code`:
        build_state, source (bytes), recipe, build_log, findings, fix_of, or
        copy_of (n: a restore or a copy keeps that version's code and checks)."""
        from app.gateway.artifacts_store import frame

        copy_of = code.get("copy_of")
        if copy_of is not None:
            src_code, src_check = self._code_rows(s, copy_of[0], copy_of[1])
            if src_code is None:
                raise InvalidRequest("That version has no build record to copy.")
            code = {
                "build_state": src_code.build_state,
                "source_hash": src_code.source_hash,
                "source_size": src_code.source_size,
                "recipe": _loads(src_code.recipe, None),
                "build_log": src_code.build_log,
                "findings": _loads(src_code.findings, []),
            }
        build_state = code.get("build_state", "ok")
        if build_state not in BUILD_STATES:
            raise InvalidRequest("Bad build state.")
        fix_of = code.get("fix_of")
        if fix_of is not None:
            self._check_fix(s, row, int(fix_of))
        auto = self._auto_fix_of(s, row, version)
        if auto is not None:
            # A tool's change of a version whose checks failed IS the automatic
            # fix, whatever its arguments said: one per turn.
            fix_of = fix_of if fix_of is not None else auto
        source_hash, source_size = code.get("source_hash"), code.get("source_size")
        if code.get("source") is not None:
            source_hash, _ = self._store_blob(s, row.owner_id, code["source"])
            source_size = len(code["source"])
            if post is not None:
                post["ensure"][source_hash] = code["source"]
        document = canon.data if canon is not None else None
        if row.kind == "webapp":
            document, build_state, code = self._store_pages(s, row, version, code, post)
        sha = frame.frame_sha256(document) if (document is not None and build_state == "ok") else None
        s.add(
            ArtifactCodeRow(
                artifact_id=row.id,
                owner_id=row.owner_id,
                n=version.n,
                build_state=build_state,
                source_hash=source_hash,
                source_size=source_size,
                recipe=json.dumps(code["recipe"]) if code.get("recipe") is not None else None,
                build_log=(code.get("build_log") or None) and str(code["build_log"])[-caps.BUILD_LOG_CHARS :],
                findings=json.dumps(list(code.get("findings") or [])[:12]),
                fix_of=fix_of,
                frame_sha256=sha,
            )
        )
        if build_state == "ok":
            check = ArtifactCheckRow(artifact_id=row.id, owner_id=row.owner_id, n=version.n, state="pending", frame_sha256=sha, heartbeat_at=time.time(), updated_at=time.time())
            if version.origin == "import":
                # Saved from a chat's outputs by the owner: no sandbox runs here;
                # the owner can ask for the checks ("Check again").
                check.state, check.result = "not_checked", json.dumps({"summary": ["saved from its chat: not checked yet"], "failures": []})
            if copy_of is not None and src_check is not None and src_check.frame_sha256 == sha and src_check.state in ("passed", "failed"):
                # The same bytes: the same result (screenshots included).
                check.state, check.result, check.shot_light, check.shot_dark = src_check.state, src_check.result, src_check.shot_light, src_check.shot_dark
            s.add(check)
        s.flush()

    def _auto_fix_of(self, s: Session, row: ArtifactRow, version: ArtifactVersionRow) -> int | None:
        """The base version when this is a tool's change of a version whose
        checks (or build) failed; FixRefused when this turn already made one."""
        if version.origin != "tool" or version.base_version is None:
            return None
        code, check = self._code_rows(s, row.id, version.base_version)
        if code is None:
            return None
        state = check_dict(check)["state"] if code.build_state == "ok" else "build_failed"
        if state not in ("failed", "build_failed"):
            return None
        # The turn: its run id; without one (a context that carries none),
        # everything since the owner last acted on the artifact counts as one.
        if version.turn_id:
            scope = ArtifactVersionRow.turn_id == version.turn_id
        else:
            since = s.execute(select(func.max(ArtifactVersionRow.n)).where(ArtifactVersionRow.artifact_id == row.id, ArtifactVersionRow.origin != "tool")).scalar_one_or_none() or 0
            scope = ArtifactVersionRow.n > since
        fixes = s.execute(
            select(func.count())
            .select_from(ArtifactCodeRow)
            .join(ArtifactVersionRow, (ArtifactVersionRow.artifact_id == ArtifactCodeRow.artifact_id) & (ArtifactVersionRow.n == ArtifactCodeRow.n))
            .where(ArtifactCodeRow.artifact_id == row.id, ArtifactCodeRow.fix_of.is_not(None), scope, ArtifactVersionRow.n != version.n)
        ).scalar_one()
        if fixes:
            raise FixRefused("This turn already made the one automatic fix of this artifact: do not run another. Tell the person what still fails; you can try again once they ask for a change.")
        return version.base_version

    def _store_pages(self, s: Session, row: ArtifactRow, version: ArtifactVersionRow, code: dict, post: dict | None) -> tuple[bytes | None, str, dict]:
        """A saved webapp: every page inlined once and stored (frame.webapp_pages)."""
        from app.gateway.artifacts_store import frame

        bundle = code.get("bundle") or {}
        files = {p: data for p, (data, _) in bundle.items()}
        entry = code.get("entry") or "index.html"
        done, failed, findings = frame.webapp_pages(files, entry)
        for path, html in done.items():
            h, _ = self._store_blob(s, row.owner_id, html)
            if post is not None:
                post["ensure"][h] = html
            s.add(ArtifactPageRow(artifact_id=row.id, owner_id=row.owner_id, n=version.n, path=path, content_hash=h, size=len(html)))
        for path, why in failed.items():
            s.add(ArtifactPageRow(artifact_id=row.id, owner_id=row.owner_id, n=version.n, path=path, error=model_line(why)[:300]))
        s.flush()
        out = {k: v for k, v in code.items() if k not in ("bundle", "entry")}
        out["findings"] = findings
        out.setdefault("recipe", {"tool": "none", "kind": "webapp", "entry": entry})
        if entry in done:
            return done[entry], "ok", out
        out["build_log"] = f"the entry page cannot be shown: {failed.get(entry, 'missing')}"
        return None, "build_failed", out

    def _check_fix(self, s: Session, row: ArtifactRow, target: int) -> None:
        """The one automatic fix (FR-018, the code_job fix_of rule): only of a
        version whose checks failed, never of a fix, and only once."""
        code, check = self._code_rows(s, row.id, target)
        if code is None:
            raise FixRefused(f"fix_of names no version of this artifact ({target}).")
        if code.fix_of is not None:
            raise FixRefused("That version was already the automatic fix: do not run another automatic fix. Tell the person what still fails; you can try again once they ask for a change.")
        state = check_dict(check)["state"] if code.build_state == "ok" else "build_failed"
        if state not in ("failed", "build_failed"):
            raise FixRefused("fix_of is only for a version whose checks failed.")
        taken = s.execute(select(func.count()).select_from(ArtifactCodeRow).where(ArtifactCodeRow.artifact_id == row.id, ArtifactCodeRow.fix_of == target)).scalar_one()
        if taken:
            raise FixRefused("That version already had its one automatic fix. Tell the person what still fails; you can try again once they ask for a change.")

    def _prune(self, s: Session, row: ArtifactRow, post: dict) -> None:
        """Beyond the per-artifact cap: drop the oldest version that is neither
        v1 nor the latest (FR-004). Nothing in S1 references older versions."""
        count = s.execute(select(func.count()).select_from(ArtifactVersionRow).where(ArtifactVersionRow.artifact_id == row.id)).scalar_one()
        while count > caps.VERSIONS_PER_ARTIFACT:
            oldest = s.execute(select(ArtifactVersionRow).where(ArtifactVersionRow.artifact_id == row.id, ArtifactVersionRow.n != 1, ArtifactVersionRow.n != row.latest_version).order_by(ArtifactVersionRow.n).limit(1)).scalar_one_or_none()
            if oldest is None:
                return
            post["gc"].add(oldest.content_hash)
            self._drop_code_rows(s, row.id, [oldest.n], post["gc"])
            s.delete(oldest)
            s.flush()
            count -= 1

    @staticmethod
    def _drop_code_rows(s: Session, artifact_id: str, ns: list[int] | None, gc: set[str]) -> None:
        where = [ArtifactCodeRow.artifact_id == artifact_id] + ([ArtifactCodeRow.n.in_(ns)] if ns is not None else [])
        for c in s.execute(select(ArtifactCodeRow).where(*where)).scalars().all():
            if c.source_hash:
                gc.add(c.source_hash)
            s.delete(c)
        cwhere = [ArtifactCheckRow.artifact_id == artifact_id] + ([ArtifactCheckRow.n.in_(ns)] if ns is not None else [])
        for c in s.execute(select(ArtifactCheckRow).where(*cwhere)).scalars().all():
            gc.update(h for h in (c.shot_light, c.shot_dark) if h)
            s.delete(c)
        pwhere = [ArtifactPageRow.artifact_id == artifact_id] + ([ArtifactPageRow.n.in_(ns)] if ns is not None else [])
        for page in s.execute(select(ArtifactPageRow).where(*pwhere)).scalars().all():
            if page.content_hash:
                gc.add(page.content_hash)
            s.delete(page)
        if ns is None:
            s.execute(delete(ArtifactBuildRow).where(ArtifactBuildRow.artifact_id == artifact_id))

    def _settle(self, owner_id: str, *, ensure: dict[str, bytes], gc: set[str]) -> None:
        """After a transaction ended, under the owner's cross-worker blob lock:
        every blob a committed version needs exists (another worker's delete
        may have unlinked it between our write and our commit), and a blob is
        unlinked only when a FRESH read finds no version referencing it. Both
        under one lock, so a delete never unlinks what a racing write just
        committed, in either order."""
        if not ensure and not gc:
            return
        with blobs.owner_lock(owner_id):
            for content_hash, data in ensure.items():
                if not blobs.path_for(owner_id, content_hash).exists():
                    blobs.write(owner_id, data)
            if gc:
                with self._read() as s:
                    for content_hash in gc:
                        if not self._refs(s, owner_id, content_hash):
                            blobs.delete(owner_id, content_hash)

    def _commit_or_cleanup(self, owner_id: str, work) -> Any:
        """Run a write, then settle its blobs. If it fails, a blob it wrote is
        removed when nothing references it."""
        post: dict = {"ensure": {}, "gc": set()}
        try:
            with self._write() as s:
                result = work(s, post)
        except IntegrityError:
            self._cleanup(owner_id, post)
            raise Stale("This artifact changed while saving; read it again.") from None
        except BaseException:
            self._cleanup(owner_id, post)
            raise
        self._settle(owner_id, ensure=post["ensure"], gc=post["gc"])
        return result

    def _cleanup(self, owner_id: str, post: dict) -> None:
        try:
            self._settle(owner_id, ensure={}, gc=set(post["ensure"]))
        except Exception:  # noqa: BLE001 — an orphan blob is harmless; logged
            logger.warning("artifact store: could not remove an orphan blob")

    def create(
        self,
        owner_id: str,
        *,
        kind: str,
        title: str,
        canon: Canonical | None,
        lineage: str,
        lineage_source: str | None,
        origin: str,
        note: str | None = None,
        thread_id: str | None = None,
        turn_id: str | None = None,
        tool_call_id: str | None = None,
        imported_from: str | None = None,
        chat_ref: tuple[str, int, str] | None = None,
        saved: bool = False,
        bundle: dict[str, tuple[bytes, str]] | None = None,
        code: dict | None = None,
    ) -> tuple[dict, dict]:
        """A new artifact. Unsaved unless `saved` (only the owner's own actions
        pass it: duplicate, "Save to artifacts"). `bundle` ({path: (bytes,
        media_type)}) is a webapp's file set; `canon` is then its manifest."""
        clean = clean_title(title)

        def work(s: Session, post: dict) -> tuple[dict, dict]:
            now = time.time()
            row = ArtifactRow(
                id=new_id(),
                owner_id=owner_id,
                kind=kind,
                title=clean,
                origin_thread_id=thread_id,
                origin_turn_id=turn_id,
                imported_from=imported_from,
                latest_version=1,
                pinned=False,
                saved=bool(saved),
                saved_at=now if saved else None,
                created_at=now,
                updated_at=now,
            )
            s.add(row)
            s.flush()
            extra = code
            if bundle:
                self._store_bundle(s, row, 1, bundle, post)
                if kind == "webapp":
                    extra = {**(code or {}), "bundle": bundle}
            version = self._insert_version(
                s, row, canon, n=1, base_version=None, lineage=lineage, lineage_source=lineage_source, origin=origin, note=note, thread_id=thread_id, turn_id=turn_id, tool_call_id=tool_call_id, chat_ref=chat_ref, post=post, code=extra
            )
            return self._summary(s, row), self._vdict(s, row.kind, version)

        return self._commit_or_cleanup(owner_id, work)

    def add_version(
        self,
        owner_id: str,
        artifact_id: str,
        *,
        base_version: int,
        canon: Canonical | None = None,
        build=None,
        lineage: str,
        lineage_source: str | None,
        origin: str,
        note: str | None = None,
        thread_id: str | None = None,
        turn_id: str | None = None,
        tool_call_id: str | None = None,
        chat_ref: tuple[str, int, str] | None = None,
        code: dict | None = None,
    ) -> tuple[dict, dict]:
        """A new version on top of `base_version`, which must be the latest.

        `build(session, row)` may compute the content from the latest
        version inside the same transaction (edits, restore, owner edits), always
        validated as the artifact's own kind, so a kind never changes."""

        def work(s: Session, post: dict) -> tuple[dict, dict]:
            row = self._artifact(s, owner_id, artifact_id)
            if row.archived_at is not None:
                raise Archived("This artifact is archived; restore it from the archive first.")
            if base_version != row.latest_version:
                raise Stale(f"This artifact changed: the latest version is {row.latest_version}.", current_version=row.latest_version)
            content = canon
            extra = code
            if build is not None:
                content = build(s, row)
                if isinstance(content, tuple):
                    # (content, code): a build that computes the code record too.
                    content, extra = content
            version = self._insert_version(
                s,
                row,
                content,
                n=row.latest_version + 1,
                base_version=base_version,
                lineage=lineage,
                lineage_source=lineage_source,
                origin=origin,
                note=note,
                thread_id=thread_id,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                chat_ref=chat_ref,
                post=post,
                code=extra,
            )
            if origin in ("owner_edit", "restore"):
                self._owner_intent(row)
            self._prune(s, row, post)
            return self._summary(s, row), self._vdict(s, row.kind, version)

        return self._commit_or_cleanup(owner_id, work)

    def latest_bytes(self, s: Session, row: ArtifactRow) -> bytes:
        v = self._version(s, row.owner_id, row.id, row.latest_version)
        if v.stored != "blob":
            raise InvalidRequest("This version lives in its chat and cannot be changed here.")
        return blobs.read(row.owner_id, v.content_hash)

    def restore(self, owner_id: str, artifact_id: str, *, version: int, base_version: int) -> tuple[dict, dict]:
        # The restored text is the old version's, so it keeps that version's
        # lineage (a version never changes, so reading it first is safe).
        with self._read() as s:
            self._artifact(s, owner_id, artifact_id)
            source = self._version(s, owner_id, artifact_id, version)
            lineage, lineage_source = source.lineage, source.lineage_source

        def build(s: Session, row: ArtifactRow) -> Canonical:
            if row.kind == "webapp":
                raise InvalidRequest("A web app is saved once and has no other versions to restore.")
            old = self._version(s, owner_id, artifact_id, version)
            if old.stored != "blob":
                raise InvalidRequest("This version lives in its chat and cannot be restored here.")
            data = blobs.read(owner_id, old.content_hash)
            search = None
            if row.kind in SEARCH_KINDS:
                from app.gateway.artifacts_store.kinds import text_of

                search = text_of(row.kind, data)
            canon = Canonical(data, old.media_type, old.language, search)
            if row.kind in CODE_KINDS:
                return canon, {"copy_of": (artifact_id, version)}
            return canon

        return self.add_version(owner_id, artifact_id, base_version=base_version, build=build, lineage=lineage, lineage_source=lineage_source, origin="restore", note=f"Restored version {version}")

    def patch(self, owner_id: str, artifact_id: str, *, title: str | None = None, pinned: bool | None = None) -> dict:
        with self._write() as s:
            row = self._artifact(s, owner_id, artifact_id)
            if title is not None:
                row.title = clean_title(title)
                self._owner_intent(row)
            if pinned is not None:
                if row.archived_at is not None and pinned:
                    raise Archived("An archived artifact cannot be pinned.")
                row.pinned = bool(pinned)
                if pinned:  # a pinned item is one the owner keeps
                    self._owner_intent(row)
            row.updated_at = time.time()
            s.flush()
            return self._summary(s, row)

    def set_archived(self, owner_id: str, artifact_id: str, archived: bool) -> dict:
        with self._write() as s:
            row = self._artifact(s, owner_id, artifact_id)
            if archived and row.archived_at is None:
                row.archived_at = time.time()
                row.pinned = False
                row.updated_at = row.archived_at
            elif not archived and row.archived_at is not None:
                row.archived_at = None
                row.updated_at = time.time()
            s.flush()
            return self._summary(s, row)

    def duplicate(self, owner_id: str, artifact_id: str, *, version: int | None = None, title: str | None = None) -> dict:
        with self._read() as s:
            row = self._artifact(s, owner_id, artifact_id)
            v = self._version(s, owner_id, artifact_id, version if version is not None else row.latest_version)
            if v.stored != "blob" or row.kind == "webapp":
                raise InvalidRequest("This version cannot be copied here.")
            data = blobs.read(owner_id, v.content_hash)
            kind, src_title, lineage, source, n = row.kind, row.title, v.lineage, v.lineage_source, v.n
            canon = Canonical(data, v.media_type, v.language)
        search = None
        if kind in SEARCH_KINDS:
            from app.gateway.artifacts_store.kinds import text_of

            search = text_of(kind, data)
        canon = Canonical(canon.data, canon.media_type, canon.language, search)
        summary, _ = self.create(
            owner_id,
            kind=kind,
            title=title if title is not None else f"{src_title} (copy)"[: caps.TITLE_CHARS],
            canon=canon,
            lineage=lineage,
            lineage_source=source,
            origin="duplicate",
            note=f"Copied from version {n} of another artifact",
            saved=True,
            code={"copy_of": (artifact_id, n)} if kind in CODE_KINDS else None,
        )
        return summary

    def set_saved(self, owner_id: str, artifact_id: str, saved: bool) -> dict:
        """The owner's Save / Unsave (owner session routes only; no tool)."""
        with self._write() as s:
            row = self._artifact(s, owner_id, artifact_id)
            if saved and not row.saved:
                row.saved, row.saved_at = True, time.time()
            elif not saved and row.saved:
                row.saved, row.saved_at, row.pinned = False, None, False
            s.flush()
            return self._summary(s, row)

    @staticmethod
    def _purge(s: Session, row: ArtifactRow) -> set[str]:
        """Remove a record, its versions and bundle rows; the blob hashes to
        re-check after the commit."""
        hashes = {h for (h,) in s.execute(select(ArtifactVersionRow.content_hash).where(ArtifactVersionRow.artifact_id == row.id, ArtifactVersionRow.stored == "blob"))}
        hashes |= {h for (h,) in s.execute(select(ArtifactBundleFileRow.content_hash).where(ArtifactBundleFileRow.artifact_id == row.id))}
        ArtifactStore._drop_code_rows(s, row.id, None, hashes)
        s.execute(delete(ArtifactVersionRow).where(ArtifactVersionRow.artifact_id == row.id))
        s.execute(delete(ArtifactBundleFileRow).where(ArtifactBundleFileRow.artifact_id == row.id))
        for imp in s.execute(select(ArtifactImportRow).where(ArtifactImportRow.owner_id == row.owner_id, ArtifactImportRow.artifact_id == row.id)).scalars():
            imp.artifact_id = None
        s.delete(row)
        s.flush()
        return hashes

    def mark_origin_deleted(self, owner_id: str, thread_id: str) -> int:
        """The owner deleted this chat. Its artifacts are KEPT (saved or not);
        they are only marked, so the UI can say "from a chat you deleted"."""
        with self._write() as s:
            rows = s.execute(select(ArtifactRow).where(ArtifactRow.owner_id == owner_id, ArtifactRow.origin_thread_id == thread_id)).scalars().all()
            for row in rows:
                row.origin_deleted = True
            return len(rows)

    @staticmethod
    def _owner_intent(row: ArtifactRow) -> None:
        """An owner edit, restore, rename or pin keeps the artifact: saved
        (the same rule the one-time migration applied to older artifacts)."""
        if not row.saved:
            row.saved, row.saved_at = True, time.time()

    def prune_unsaved(self, owner_id: str, *, older_than_days: float, now: float | None = None) -> int:
        """The optional sweep (OFF unless configured): unsaved, unpinned,
        unarchived artifacts not changed for `older_than_days`. Never a saved one."""
        cutoff = (now if now is not None else time.time()) - older_than_days * 86400
        hashes: set[str] = set()
        with self._write() as s:
            rows = (
                s.execute(
                    select(ArtifactRow).where(
                        ArtifactRow.owner_id == owner_id,
                        ArtifactRow.saved.is_(False),
                        ArtifactRow.pinned.is_(False),
                        ArtifactRow.archived_at.is_(None),
                        ArtifactRow.updated_at < cutoff,
                        # Anything the owner touched is spared even if unsaved.
                        ArtifactRow.id.not_in(select(ArtifactVersionRow.artifact_id).where(ArtifactVersionRow.origin.in_(("owner_edit", "restore", "duplicate")))),
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                hashes |= self._purge(s, row)
        self._settle(owner_id, ensure={}, gc=hashes)
        return len(rows)

    def owners(self) -> list[str]:
        with self._read() as s:
            return [o for (o,) in s.execute(select(ArtifactRow.owner_id).distinct())]

    def _store_bundle(self, s: Session, row: ArtifactRow, n: int, bundle: dict[str, tuple[bytes, str]], post: dict) -> None:
        """A webapp's files: one quota check for the new bytes, then each blob
        and its row (made sure of again after the commit, like any blob)."""
        new = {}
        for path, (data, _) in bundle.items():
            h = blobs.sha256(data)
            if h not in new and not self._refs(s, row.owner_id, h):
                new[h] = len(data)
        used = self._usage(s, row.owner_id)
        if used + sum(new.values()) > caps.OWNER_BYTES:
            raise QuotaExceeded("Your artifact store is full.", used=used, cap=caps.OWNER_BYTES, size=sum(new.values()))
        for path, (data, media_type) in sorted(bundle.items()):
            h = blobs.write(row.owner_id, data)
            post["ensure"][h] = data
            s.add(ArtifactBundleFileRow(owner_id=row.owner_id, artifact_id=row.id, n=n, path=path, content_hash=h, size=len(data), media_type=media_type[:100]))
        s.flush()

    def bundle_files(self, owner_id: str, artifact_id: str, n: int) -> list[dict]:
        with self._read() as s:
            rows = s.execute(select(ArtifactBundleFileRow).where(ArtifactBundleFileRow.owner_id == owner_id, ArtifactBundleFileRow.artifact_id == artifact_id, ArtifactBundleFileRow.n == n).order_by(ArtifactBundleFileRow.path)).scalars()
            return [{"path": r.path, "size": r.size, "media_type": r.media_type, "content_hash": r.content_hash} for r in rows]

    def delete(self, owner_id: str, artifact_id: str, *, confirm_id: str, version_count: int) -> None:
        # Blobs are unlinked only AFTER the delete commits, each re-checked
        # under the owner's blob lock (_settle).
        with self._write() as s:
            row = self._artifact(s, owner_id, artifact_id)
            if row.archived_at is None:
                raise NotArchived("Only an archived artifact can be deleted permanently. Archive it first.")
            count = s.execute(select(func.count()).select_from(ArtifactVersionRow).where(ArtifactVersionRow.artifact_id == row.id)).scalar_one()
            if confirm_id != row.id or version_count != count:
                raise Mismatch("The confirmation does not match this artifact; nothing was deleted.", version_count=int(count))
            hashes = self._purge(s, row)
        self._settle(owner_id, ensure={}, gc=hashes)

    # -- code kinds (Slice 2) -------------------------------------------------------------

    def code_version(self, owner_id: str, artifact_id: str, n: int) -> tuple[dict, ArtifactVersionRow, ArtifactCodeRow, ArtifactCheckRow | None]:
        """(summary, version row, code row, checks row) of a code version."""
        with self._read() as s:
            row = self._artifact(s, owner_id, artifact_id)
            v = self._version(s, owner_id, artifact_id, n)
            code, check = self._code_rows(s, artifact_id, n)
            if row.kind not in CODE_KINDS or code is None:
                raise InvalidRequest("This artifact is not a code kind.")
            return self._summary(s, row), v, code, check

    def check_fix(self, owner_id: str, artifact_id: str, target: int) -> None:
        """Raise FixRefused when `fix_of=target` breaks the one-fix rule."""
        with self._read() as s:
            self._check_fix(s, self._artifact(s, owner_id, artifact_id), target)

    def page_document(self, owner_id: str, artifact_id: str, n: int, path: str | None = None) -> bytes:
        """The document a code version shows before the shim: html and react
        their stored document (no path); webapp its stored, already inlined
        page at `path` (default: its entry). InvalidRequest otherwise."""
        with self._read() as s:
            row = self._artifact(s, owner_id, artifact_id)
            v = self._version(s, owner_id, artifact_id, n)
            code, _ = self._code_rows(s, artifact_id, n)
            if row.kind not in CODE_KINDS or code is None or code.build_state != "ok" or v.stored != "blob":
                raise InvalidRequest("This version has no document to show.")
            if row.kind != "webapp":
                if path is not None:
                    raise InvalidRequest("Only a web app has pages.")
                return blobs.read(owner_id, v.content_hash)
            if path is None:
                path = _loads(code.recipe, {}).get("entry") or "index.html"
            page = s.execute(select(ArtifactPageRow).where(ArtifactPageRow.artifact_id == artifact_id, ArtifactPageRow.n == n, ArtifactPageRow.path == path)).scalar_one_or_none()
            if page is None or not page.content_hash:
                raise InvalidRequest("No such page in this web app.")
            h = page.content_hash
        return blobs.read(owner_id, h)

    def pages(self, owner_id: str, artifact_id: str, n: int) -> list[dict]:
        with self._read() as s:
            self._artifact(s, owner_id, artifact_id)
            rows = s.execute(select(ArtifactPageRow).where(ArtifactPageRow.artifact_id == artifact_id, ArtifactPageRow.owner_id == owner_id, ArtifactPageRow.n == n).order_by(ArtifactPageRow.path)).scalars().all()
            return [{"path": r.path, "ok": r.content_hash is not None, "reason": r.error} for r in rows]

    def consume_frame_nonce(self, nonce: str, expires_at: float) -> bool:
        """True the FIRST time a view token's nonce is used (any worker)."""
        from omniharness.persistence.artifacts.model import ArtifactFrameUseRow

        try:
            with self._write() as s:
                s.execute(delete(ArtifactFrameUseRow).where(ArtifactFrameUseRow.expires_at < time.time() - 60))
                s.add(ArtifactFrameUseRow(nonce=nonce, expires_at=expires_at))
                s.flush()
            return True
        except IntegrityError:
            return False

    def source(self, owner_id: str, code: ArtifactCodeRow) -> bytes | None:
        return blobs.read(owner_id, code.source_hash) if code.source_hash else None

    def beat_check(self, owner_id: str, artifact_id: str, n: int) -> None:
        with self._write() as s:
            check = s.execute(select(ArtifactCheckRow).where(ArtifactCheckRow.owner_id == owner_id, ArtifactCheckRow.artifact_id == artifact_id, ArtifactCheckRow.n == n)).scalar_one_or_none()
            if check is not None and check.state == "pending":
                check.heartbeat_at = time.time()

    def restart_check(self, owner_id: str, artifact_id: str, n: int) -> bool:
        """A check that gave no answer (or stopped) may be run again."""
        with self._write() as s:
            check = s.execute(select(ArtifactCheckRow).where(ArtifactCheckRow.owner_id == owner_id, ArtifactCheckRow.artifact_id == artifact_id, ArtifactCheckRow.n == n)).scalar_one_or_none()
            if check is None or check_dict(check)["state"] != "not_checked":
                return False
            check.state, check.result, check.heartbeat_at, check.updated_at = "pending", None, time.time(), time.time()
            return True

    def set_check(self, owner_id: str, artifact_id: str, n: int, *, state: str, result: dict, frame_sha256: str, shots: dict[str, bytes] | None = None) -> None:
        """The checks' answer for one version. Recorded only for the bytes they
        checked (`frame_sha256` must be the version's own): a result for other
        bytes is refused (not_checked)."""
        if state not in CHECK_STATES or state == "pending":
            raise InvalidRequest("Bad check state.")

        def work(s: Session, post: dict) -> None:
            check = s.execute(select(ArtifactCheckRow).where(ArtifactCheckRow.owner_id == owner_id, ArtifactCheckRow.artifact_id == artifact_id, ArtifactCheckRow.n == n)).scalar_one_or_none()
            if check is None:
                return
            final = state
            data = dict(result)
            if check.frame_sha256 != frame_sha256:
                final = "not_checked"
                data = {"summary": ["the checks did not check this version's own document"], "failures": []}
            check.state = final
            check.result = json.dumps(data)[:200_000]
            for theme in ("light", "dark"):
                png = (shots or {}).get(theme) if final in ("passed", "failed") else None
                if png:
                    h, _ = self._store_blob(s, owner_id, png)
                    post["ensure"][h] = png
                    old = getattr(check, f"shot_{theme}")
                    if old and old != h:
                        post["gc"].add(old)
                    setattr(check, f"shot_{theme}", h)
            check.updated_at = time.time()
            check.heartbeat_at = check.updated_at

        self._commit_or_cleanup(owner_id, work)

    def shot(self, owner_id: str, artifact_id: str, n: int, theme: str) -> bytes | None:
        with self._read() as s:
            self._artifact(s, owner_id, artifact_id)
            _, check = self._code_rows(s, artifact_id, n)
            h = getattr(check, f"shot_{theme}", None) if check is not None and theme in ("light", "dark") else None
        return blobs.read(owner_id, h) if h else None

    def start_build(self, owner_id: str, artifact_id: str, base_version: int) -> None:
        """Record an owner's Rebuild as running; refused while another one
        is alive (its worker beat within LIVENESS_SECONDS)."""
        with self._write() as s:
            row = self._artifact(s, owner_id, artifact_id)
            if row.kind != "react":
                raise NotEditable("Only react artifacts are rebuilt.")
            if row.archived_at is not None:
                raise Archived("This artifact is archived; restore it from the archive first.")
            if base_version != row.latest_version:
                raise Stale(f"This artifact changed: the latest version is {row.latest_version}.", current_version=row.latest_version)
            build = s.execute(select(ArtifactBuildRow).where(ArtifactBuildRow.artifact_id == artifact_id)).scalar_one_or_none()
            now = time.time()
            if build is not None and build.state == "running" and now - build.heartbeat_at <= LIVENESS_SECONDS:
                raise BuildBusy("A build of this artifact is already running.")
            if build is None:
                build = ArtifactBuildRow(artifact_id=artifact_id, owner_id=owner_id, state="running", base_version=base_version, started_at=now, heartbeat_at=now)
                s.add(build)
            build.state, build.base_version, build.reason, build.result_version, build.started_at, build.heartbeat_at = "running", base_version, None, None, now, now

    def beat_build(self, owner_id: str, artifact_id: str) -> None:
        with self._write() as s:
            build = s.execute(select(ArtifactBuildRow).where(ArtifactBuildRow.owner_id == owner_id, ArtifactBuildRow.artifact_id == artifact_id)).scalar_one_or_none()
            if build is not None and build.state == "running":
                build.heartbeat_at = time.time()

    def end_build(self, owner_id: str, artifact_id: str, *, state: str, reason: str | None = None, result_version: int | None = None) -> None:
        with self._write() as s:
            build = s.execute(select(ArtifactBuildRow).where(ArtifactBuildRow.owner_id == owner_id, ArtifactBuildRow.artifact_id == artifact_id)).scalar_one_or_none()
            if build is not None:
                build.state, build.reason, build.result_version, build.heartbeat_at = state, (model_line(reason)[:300] if reason else None), result_version, time.time()

    # -- importer bookkeeping (FR-037) ------------------------------------------------

    def import_existing(self, owner_id: str, thread_id: str, path: str, content_hash: str) -> dict | None:
        """The live artifact an earlier "Save to artifacts" of this exact file made."""
        with self._read() as s:
            q = select(ArtifactImportRow.artifact_id).where(
                ArtifactImportRow.owner_id == owner_id, ArtifactImportRow.thread_id == thread_id, ArtifactImportRow.path == path, ArtifactImportRow.content_hash == content_hash, ArtifactImportRow.artifact_id.is_not(None)
            )
            for (artifact_id,) in s.execute(q):
                row = s.execute(select(ArtifactRow).where(ArtifactRow.id == artifact_id, ArtifactRow.owner_id == owner_id)).scalar_one_or_none()
                if row is not None:
                    return self._summary(s, row)
        return None

    def record_import(self, owner_id: str, thread_id: str, path: str, content_hash: str, artifact_id: str | None, *, size: int | None = None, mtime_ns: int | None = None) -> None:
        try:
            with self._write() as s:
                s.add(ArtifactImportRow(owner_id=owner_id, thread_id=thread_id, path=path, content_hash=content_hash, artifact_id=artifact_id, size=size, mtime_ns=mtime_ns, created_at=time.time()))
        except IntegrityError:
            pass  # another worker recorded it first: idempotent
