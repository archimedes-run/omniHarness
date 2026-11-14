"""One research budget per person's turn, shared by every agent working on it.

Why this exists (live chat, 2026-11-14: 19 web searches over 7+ minutes for
"who is <person>", no answer): TurnBudgetMiddleware counted lookups from the
turn's messages in state. The summarizer replaces the turn's earlier messages
with one summary message, so after each summary the count started again from
the few messages it kept, and the research clock (keyed by the turn's first
message id, which became the summary's id) restarted too. The research
subagent and the `task` subagents also counted only their own messages.

This ledger is the count. It lives in the process, keyed by thread, and holds
the CURRENT turn of that thread (turn key: the id of the person's message that
started it, carried through a summary by its turn record). The lead opens it;
the research tool's and every subagent's lookups are reserved in the same
ledger by thread id. A reservation is checked and counted under one lock, so
parallel calls of one reply can never pass the cap together.

A turn resumed in another process (after a confirmation) is seeded from the
turn's own messages and the summary record's tool list, so the count is never
lower than what the messages show.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

SEARCH_TOOLS = frozenset({"web_search", "image_search"})
FETCH_TOOLS = frozenset({"web_fetch"})
RESEARCH_TOOLS = frozenset({"research"})
LOOKUP_TOOLS = SEARCH_TOOLS | FETCH_TOOLS | RESEARCH_TOOLS

#: Words that do not change what a search looks for.
_STOPWORDS = frozenset("a an the of in on at to for from by with and or is are was were be who whom whose what which about info information details detail please find search look up lookup me tell more latest recent".split())


def query_terms(query: str) -> str:
    """A search's normalised terms: case, accents, punctuation, word order and
    filler words ignored. "Who is Jane Roe?" and "jane roe" are the same search."""
    text = unicodedata.normalize("NFKD", query or "").encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z0-9]+", text)
    kept = sorted({w for w in words if w not in _STOPWORDS})
    return " ".join(kept) or " ".join(sorted(set(words)))


@dataclass
class Caps:
    searches: int
    fetches: int
    research: int
    seconds: float


@dataclass
class TurnLedger:
    thread_id: str
    turn_key: str
    caps: Caps
    run_id: str = ""
    started: float = 0.0
    searches: int = 0
    fetches: set[str] = field(default_factory=set)
    research: int = 0
    #: normalised terms -> the query as first asked
    queries: dict[str, str] = field(default_factory=dict)
    budget_refusals: int = 0
    refusals: int = 0
    #: Why tool calls ended for this turn ("search budget", "research time", ...), or "".
    stopped: str = ""

    def elapsed(self, now: float) -> float:
        return max(0.0, now - self.started)


#: Reservation outcomes.
OK = "ok"
OVER_SEARCHES = "search"
OVER_FETCHES = "fetch"
OVER_RESEARCH = "research"
OUT_OF_TIME = "time"
REPEAT = "repeat"


class ResearchLedgers:
    """Every thread's current turn ledger in this process."""

    def __init__(self, clock: Any = time.monotonic) -> None:
        self._lock = threading.Lock()
        self._by_thread: dict[str, TurnLedger] = {}
        self._clock = clock

    def open(self, thread_id: str, turn_key: str, caps: Caps, *, run_id: str = "", seed: dict | None = None) -> TurnLedger:
        """The thread's ledger for this turn, created (and seeded from the
        turn's messages) when the turn is new. A new run of the same turn (a
        resume after a confirmation) keeps the counts and starts its own
        research clock: the time the person spent answering a card is not
        research time."""
        now = self._clock()
        with self._lock:
            ledger = self._by_thread.get(thread_id)
            if ledger is None or ledger.turn_key != turn_key:
                ledger = TurnLedger(thread_id=thread_id, turn_key=turn_key, caps=caps, run_id=run_id, started=now)
                if seed:
                    ledger.searches = int(seed.get("searches") or 0)
                    ledger.fetches = set(seed.get("fetches") or ())
                    ledger.research = int(seed.get("research") or 0)
                    ledger.queries = dict(seed.get("queries") or {})
                self._by_thread[thread_id] = ledger
                if len(self._by_thread) > 1024:
                    for old in list(self._by_thread)[:512]:
                        if old != thread_id:
                            self._by_thread.pop(old, None)
            else:
                # The caps are the turn's, fixed when it opened (from the
                # person's message); a later call never rescales them.
                if run_id and ledger.run_id != run_id:
                    ledger.run_id = run_id
                    ledger.started = now
                    ledger.stopped = ""
                    ledger.budget_refusals = 0
                    ledger.refusals = 0
            return ledger

    def current(self, thread_id: str) -> TurnLedger | None:
        with self._lock:
            return self._by_thread.get(thread_id)

    def reserve(self, ledger: TurnLedger, name: str, args: dict, *, extra: TurnLedger | None = None) -> tuple[str, str]:
        """Check and count one lookup, atomically. Returns (outcome, detail).
        `extra`: a second ledger the call must also fit (a subagent's own,
        per-call budget beside the turn's)."""
        now = self._clock()
        with self._lock:
            ledgers = [ledger] + ([extra] if extra is not None else [])
            for one in ledgers:
                outcome = self._check(one, name, args, now)
                if outcome[0] != OK:
                    self._refused(ledgers, outcome[0])
                    return outcome
            for one in ledgers:
                self._count(one, name, args)
            return OK, ""

    def _check(self, ledger: TurnLedger, name: str, args: dict, now: float) -> tuple[str, str]:
        if name not in LOOKUP_TOOLS:
            return OK, ""
        if ledger.elapsed(now) >= ledger.caps.seconds:
            return OUT_OF_TIME, str(int(ledger.caps.seconds))
        if name in SEARCH_TOOLS:
            terms = query_terms(str((args or {}).get("query") or ""))
            if terms and terms in ledger.queries:
                return REPEAT, ledger.queries[terms]
            if ledger.searches >= ledger.caps.searches:
                return OVER_SEARCHES, str(ledger.caps.searches)
        if name in FETCH_TOOLS:
            url = _url_key(args)
            if url not in ledger.fetches and len(ledger.fetches) >= ledger.caps.fetches:
                return OVER_FETCHES, str(ledger.caps.fetches)
        if name in RESEARCH_TOOLS and ledger.research >= ledger.caps.research:
            return OVER_RESEARCH, str(ledger.caps.research)
        return OK, ""

    @staticmethod
    def _count(ledger: TurnLedger, name: str, args: dict) -> None:
        if name in SEARCH_TOOLS:
            ledger.searches += 1
            query = str((args or {}).get("query") or "")
            terms = query_terms(query)
            if terms:
                ledger.queries.setdefault(terms, query)
        elif name in FETCH_TOOLS:
            ledger.fetches.add(_url_key(args))
        elif name in RESEARCH_TOOLS:
            ledger.research += 1

    @staticmethod
    def _refused(ledgers: list[TurnLedger], outcome: str) -> None:
        for one in ledgers:
            one.refusals += 1
            if outcome != REPEAT:
                one.budget_refusals += 1

    def release(self, ledger: TurnLedger, name: str, args: dict) -> None:
        """Give back a reservation whose call did not run as a lookup (a
        card, a refusal by the policy layer, an error)."""
        with self._lock:
            if name in SEARCH_TOOLS and ledger.searches > 0:
                ledger.searches -= 1
                terms = query_terms(str((args or {}).get("query") or ""))
                if ledger.queries.get(terms) == str((args or {}).get("query") or ""):
                    ledger.queries.pop(terms, None)
            elif name in FETCH_TOOLS:
                ledger.fetches.discard(_url_key(args))
            elif name in RESEARCH_TOOLS and ledger.research > 0:
                ledger.research -= 1

    def stop(self, ledger: TurnLedger, why: str) -> None:
        with self._lock:
            ledger.stopped = ledger.stopped or why


def _url_key(args: Any) -> str:
    from urllib.parse import urldefrag

    url = str((args or {}).get("url") or "") if isinstance(args, dict) else ""
    return urldefrag(url)[0]


_LEDGERS = ResearchLedgers()


def ledgers() -> ResearchLedgers:
    return _LEDGERS


def reset_for_tests(clock: Any = time.monotonic) -> ResearchLedgers:
    global _LEDGERS
    _LEDGERS = ResearchLedgers(clock)
    return _LEDGERS
