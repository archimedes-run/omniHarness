"""The coding-job store: jobs, their steps and their model calls (spec 009).

SQLite under the data dir, shared by every gateway worker: the job runs in the
worker that ran the tool, the LLM proxy in whichever worker holds its port,
and Stop or a job card's poll may land on any of them. WAL mode, short
transactions, and every budget decision is one transaction.

Nothing secret is stored: the job token is never written; steps hold the
worker's commands and outputs, which pass through the display sanitiser and
the known-secrets redaction first, and are capped.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

RUNNING = "running"
INFLIGHT = "inflight"
#: A reservation older than this never settled: its process died.
STALE_INFLIGHT_S = 900
#: Terminal statuses. Only `verified` may ever be reported as done.
TERMINAL = frozenset({"verified", "unverified", "failed", "stopped", "blocked"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  tool_call_id TEXT NOT NULL,
  title TEXT NOT NULL,
  project_dir TEXT NOT NULL,
  container TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  phase TEXT NOT NULL DEFAULT 'starting',
  budget_usd REAL NOT NULL,
  spent_usd REAL NOT NULL DEFAULT 0,
  calls INTEGER NOT NULL DEFAULT 0,
  stop_requested INTEGER NOT NULL DEFAULT 0,
  reason TEXT,
  result TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  finished_at REAL
);
CREATE INDEX IF NOT EXISTS jobs_thread ON jobs (thread_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_call ON jobs (thread_id, tool_call_id);
CREATE TABLE IF NOT EXISTS steps (
  job_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  at REAL NOT NULL,
  kind TEXT NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY (job_id, seq)
);
CREATE TABLE IF NOT EXISTS llm_calls (
  job_id TEXT NOT NULL,
  at REAL NOT NULL,
  container TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  cached_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL DEFAULT 0,
  reason TEXT
);
CREATE INDEX IF NOT EXISTS llm_calls_month ON llm_calls (at);
CREATE INDEX IF NOT EXISTS llm_calls_container ON llm_calls (container, at);
"""

MAX_STEP_BYTES = 16 * 1024
MAX_STEPS = 2000


@dataclass
class Job:
    id: str
    thread_id: str
    user_id: str
    tool_call_id: str
    title: str
    project_dir: str
    container: str
    model: str
    status: str
    phase: str
    budget_usd: float
    spent_usd: float
    calls: int
    stop_requested: bool
    reason: str | None
    result: dict | None
    created_at: float
    updated_at: float
    finished_at: float | None

    def public(self) -> dict:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "tool_call_id": self.tool_call_id,
            "title": self.title,
            "project_dir": self.project_dir,
            "model": self.model,
            "status": self.status,
            "phase": self.phase,
            "budget_usd": round(self.budget_usd, 4),
            "spent_usd": round(self.spent_usd, 6),
            "calls": self.calls,
            "stop_requested": self.stop_requested,
            "reason": self.reason,
            "result": self.result,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "finished_at": _iso(self.finished_at) if self.finished_at else None,
        }


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat()


def month_start(now: float | None = None) -> float:
    d = datetime.fromtimestamp(now if now is not None else time.time(), UTC)
    return datetime(d.year, d.month, 1, tzinfo=UTC).timestamp()


class CodeJobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._conn().executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        db = self._conn()
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
        except BaseException:
            db.execute("ROLLBACK")
            raise
        db.execute("COMMIT")

    # -- jobs ---------------------------------------------------------------

    def create(self, *, job_id: str, thread_id: str, user_id: str, tool_call_id: str, title: str, project_dir: str, budget_usd: float, model: str) -> Job:
        now = time.time()
        with self._tx() as db:
            db.execute(
                "INSERT INTO jobs (id, thread_id, user_id, tool_call_id, title, project_dir, model, status, budget_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, thread_id, user_id, tool_call_id, title, project_dir, model, RUNNING, budget_usd, now, now),
            )
        job = self.get(job_id)
        assert job is not None
        return job

    def get(self, job_id: str) -> Job | None:
        row = self._conn().execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _job(row) if row else None

    def by_call(self, thread_id: str, tool_call_id: str) -> Job | None:
        row = self._conn().execute("SELECT * FROM jobs WHERE thread_id = ? AND tool_call_id = ?", (thread_id, tool_call_id)).fetchone()
        return _job(row) if row else None

    def for_thread(self, thread_id: str, limit: int = 50) -> list[Job]:
        rows = self._conn().execute("SELECT * FROM jobs WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?", (thread_id, limit)).fetchall()
        return [_job(r) for r in rows]

    def running_in_thread(self, thread_id: str) -> Job | None:
        row = self._conn().execute("SELECT * FROM jobs WHERE thread_id = ? AND status = ? ORDER BY created_at DESC LIMIT 1", (thread_id, RUNNING)).fetchone()
        return _job(row) if row else None

    def running(self) -> list[Job]:
        return [_job(r) for r in self._conn().execute("SELECT * FROM jobs WHERE status = ?", (RUNNING,)).fetchall()]

    def update(self, job_id: str, **fields: object) -> None:
        if not fields:
            return
        fields["updated_at"] = time.time()
        if "result" in fields and fields["result"] is not None and not isinstance(fields["result"], str):
            fields["result"] = json.dumps(fields["result"])
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._tx() as db:
            db.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))

    def finish(self, job_id: str, *, status: str, reason: str | None, result: dict) -> bool:
        """Set the terminal status once; False if the job had already ended."""
        assert status in TERMINAL
        now = time.time()
        with self._tx() as db:
            cur = db.execute(
                "UPDATE jobs SET status = ?, phase = 'done', reason = ?, result = ?, finished_at = ?, updated_at = ? WHERE id = ? AND status = ?",
                (status, reason, json.dumps(result), now, now, job_id, RUNNING),
            )
            return cur.rowcount == 1

    def reap_stale(self, max_age: float = 90.0) -> list[str]:
        """Jobs still "running" whose runner stopped beating (its process ended):
        reported as interrupted, never resumed silently or called done."""
        reason = "the gateway restarted while the job ran"
        cutoff = time.time() - max_age
        stale = [r["id"] for r in self._conn().execute("SELECT id FROM jobs WHERE status = ? AND updated_at < ?", (RUNNING, cutoff)).fetchall()]
        for job_id in stale:
            self.finish(job_id, status="blocked", reason=reason, result={"status": "blocked", "reason": reason})
        return stale

    def beat(self, job_id: str) -> None:
        with self._tx() as db:
            db.execute("UPDATE jobs SET updated_at = ? WHERE id = ? AND status = ?", (time.time(), job_id, RUNNING))

    def request_stop(self, job_id: str) -> bool:
        with self._tx() as db:
            cur = db.execute("UPDATE jobs SET stop_requested = 1, updated_at = ? WHERE id = ? AND status = ?", (time.time(), job_id, RUNNING))
            return cur.rowcount == 1

    # -- steps --------------------------------------------------------------

    def add_step(self, job_id: str, kind: str, data: dict) -> int | None:
        encoded = json.dumps(data, ensure_ascii=False)
        if len(encoded.encode()) > MAX_STEP_BYTES:
            data = {**data, "output": _clip(str(data.get("output", "")), 2000), "truncated": True}
            encoded = json.dumps(data, ensure_ascii=False)[: MAX_STEP_BYTES * 2]
        with self._tx() as db:
            seq = db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM steps WHERE job_id = ?", (job_id,)).fetchone()[0]
            if seq > MAX_STEPS:
                return None
            db.execute("INSERT INTO steps (job_id, seq, at, kind, data) VALUES (?, ?, ?, ?, ?)", (job_id, seq, time.time(), kind, encoded))
            return seq

    def steps(self, job_id: str, after: int = 0, limit: int = 500) -> list[dict]:
        rows = self._conn().execute("SELECT seq, at, kind, data FROM steps WHERE job_id = ? AND seq > ? ORDER BY seq LIMIT ?", (job_id, after, limit)).fetchall()
        return [{"seq": r["seq"], "at": _iso(r["at"]), "kind": r["kind"], **json.loads(r["data"])} for r in rows]

    # -- model calls and money ----------------------------------------------

    def reserve_call(
        self,
        *,
        job_id: str,
        container: str,
        model: str,
        monthly_cap_usd: float,
        rate_per_minute: int,
        max_inflight: int,
        input_cost_usd: float,
        output_usd_per_token: float,
        requested_output_tokens: int,
        min_output_tokens: int = 256,
        now: float | None = None,
    ) -> tuple[int | None, str | None, int]:
        """Reserve a model call BEFORE it is forwarded: (call id, None, the
        output tokens it may use) or (None, refusal reason, 0). One transaction.

        The reservation is a row with a pessimistic cost (the input's size at
        the input price, plus every allowed output token at the output price),
        counted against the job's budget, the month's cap, the job's
        concurrent calls and the sandbox's rate until the call settles. The
        output tokens are cut to what the remaining money allows, so a call can
        never cost more than what is left. A call whose provider reports no
        usage, or that is cut short, is charged its reservation."""
        now = now if now is not None else time.time()
        with self._tx() as db:
            self._expire_stale(db, now)
            row = db.execute("SELECT status, stop_requested, spent_usd, budget_usd FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return None, "unknown job", 0
            if row["status"] != RUNNING or row["stop_requested"]:
                return None, "the job is not running", 0
            inflight = db.execute("SELECT COUNT(*), COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE job_id = ? AND status = ?", (job_id, INFLIGHT)).fetchone()
            if inflight[0] >= max_inflight:
                return None, f"too many model calls at once (at most {max_inflight})", 0
            recent = db.execute("SELECT COUNT(*) FROM llm_calls WHERE container = ? AND at >= ? AND status != 'refused'", (container, now - 60)).fetchone()[0]
            if recent >= rate_per_minute:
                return None, f"rate limit ({rate_per_minute} calls a minute)", 0
            job_left = row["budget_usd"] - row["spent_usd"] - inflight[1]
            month = db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE at >= ?", (month_start(now),)).fetchone()[0]
            month_left = monthly_cap_usd - month
            left = min(job_left, month_left)
            allowed = int((left - input_cost_usd) / output_usd_per_token) if output_usd_per_token > 0 else requested_output_tokens
            output_tokens = min(requested_output_tokens, allowed)
            if output_tokens < min_output_tokens:
                if month_left <= job_left:
                    return None, f"this month's coding-job cap (${monthly_cap_usd:.2f}) is reached", 0
                return None, f"the job's budget (${row['budget_usd']:.2f}) is spent", 0
            estimate = input_cost_usd + output_tokens * output_usd_per_token
            cur = db.execute(
                "INSERT INTO llm_calls (job_id, at, container, model, status, cost_usd) VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, now, container, model, INFLIGHT, estimate),
            )
            return int(cur.lastrowid), None, output_tokens

    def settle_call(
        self,
        call_id: int,
        *,
        status: str,
        usage: tuple[int, int, int] | None,
        cost_usd: float | None,
        latency_ms: int = 0,
        reason: str | None = None,
    ) -> float:
        """Settle a reserved call; returns what was charged. No usage (or a
        call cut short): the reservation is charged."""
        now = time.time()
        with self._tx() as db:
            row = db.execute("SELECT job_id, cost_usd, status FROM llm_calls WHERE rowid = ?", (call_id,)).fetchone()
            if row is None or row["status"] != INFLIGHT:
                return 0.0
            charged = row["cost_usd"] if (usage is None or cost_usd is None) else cost_usd
            inp, cached, out = usage or (0, 0, 0)
            db.execute(
                "UPDATE llm_calls SET status = ?, input_tokens = ?, cached_tokens = ?, output_tokens = ?, cost_usd = ?, latency_ms = ?, reason = ? WHERE rowid = ?",
                (status if usage is not None else f"{status}-estimated", inp, cached, out, charged, latency_ms, reason, call_id),
            )
            db.execute("UPDATE jobs SET spent_usd = spent_usd + ?, calls = calls + 1, updated_at = ? WHERE id = ?", (charged, now, row["job_id"]))
            return float(charged)

    @staticmethod
    def _expire_stale(db: sqlite3.Connection, now: float) -> None:
        """A reservation whose call never settled (the process died): charged."""
        for row in db.execute("SELECT rowid, job_id, cost_usd FROM llm_calls WHERE status = ? AND at < ?", (INFLIGHT, now - STALE_INFLIGHT_S)).fetchall():
            db.execute("UPDATE llm_calls SET status = 'lost-estimated' WHERE rowid = ?", (row[0],))
            db.execute("UPDATE jobs SET spent_usd = spent_usd + ? WHERE id = ?", (row[2], row[1]))

    def record_call(
        self,
        *,
        job_id: str,
        container: str,
        model: str,
        status: str,
        input_tokens: int = 0,
        cached_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        latency_ms: int = 0,
        reason: str | None = None,
    ) -> None:
        now = time.time()
        with self._tx() as db:
            db.execute(
                "INSERT INTO llm_calls (job_id, at, container, model, status, input_tokens, cached_tokens, output_tokens, cost_usd, latency_ms, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, now, container, model, status, input_tokens, cached_tokens, output_tokens, cost_usd, latency_ms, reason),
            )
            if status == "ok":
                db.execute("UPDATE jobs SET spent_usd = spent_usd + ?, calls = calls + 1, updated_at = ? WHERE id = ?", (cost_usd, now, job_id))

    def last_refusal(self, job_id: str, kinds: tuple[str, ...]) -> str | None:
        """The latest refusal the proxy itself recorded for this job whose
        reason names one of `kinds` (e.g. budget, cap)."""
        for row in self._conn().execute("SELECT reason FROM llm_calls WHERE job_id = ? AND status = 'refused' ORDER BY at DESC LIMIT 50", (job_id,)).fetchall():
            if row[0] and any(k in row[0] for k in kinds):
                return row[0]
        return None

    def job_calls(self, job_id: str) -> list[dict]:
        rows = self._conn().execute("SELECT * FROM llm_calls WHERE job_id = ? ORDER BY at", (job_id,)).fetchall()
        return [dict(r) for r in rows]

    def month_spend(self, now: float | None = None, *, user_id: str | None = None) -> float:
        """All jobs' spend this month (the cap's measure), or one user's own."""
        if user_id is None:
            return float(self._conn().execute("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE at >= ?", (month_start(now),)).fetchone()[0])
        sql = "SELECT COALESCE(SUM(c.cost_usd), 0) FROM llm_calls c JOIN jobs j ON j.id = c.job_id WHERE c.at >= ? AND j.user_id = ?"
        return float(self._conn().execute(sql, (month_start(now), user_id)).fetchone()[0])

    def delete_thread(self, thread_id: str) -> list[str]:
        """Forget a deleted thread's jobs, steps and model-call rows; returns their ids."""
        with self._tx() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM jobs WHERE thread_id = ?", (thread_id,)).fetchall()]
            for job_id in ids:
                db.execute("DELETE FROM steps WHERE job_id = ?", (job_id,))
                # Money already spent still counts toward the month's cap.
                db.execute("UPDATE llm_calls SET job_id = 'deleted', container = 'deleted' WHERE job_id = ?", (job_id,))
                db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            return ids


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n // 2] + "\n…\n" + text[-n // 2 :]


def _job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        thread_id=row["thread_id"],
        user_id=row["user_id"],
        tool_call_id=row["tool_call_id"],
        title=row["title"],
        project_dir=row["project_dir"],
        container=row["container"],
        model=row["model"],
        status=row["status"],
        phase=row["phase"],
        budget_usd=row["budget_usd"],
        spent_usd=row["spent_usd"],
        calls=row["calls"],
        stop_requested=bool(row["stop_requested"]),
        reason=row["reason"],
        result=json.loads(row["result"]) if row["result"] else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        finished_at=row["finished_at"],
    )
