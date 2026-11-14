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
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

SEARCH_TOOLS = frozenset({"web_search", "image_search"})
FETCH_TOOLS = frozenset({"web_fetch"})
RESEARCH_TOOLS = frozenset({"research"})
LOOKUP_TOOLS = SEARCH_TOOLS | FETCH_TOOLS | RESEARCH_TOOLS

#: The lead's current turn key while one of its tool calls runs: a subagent
#: started by that call joins THAT turn's ledger only (subagent context key).
CURRENT_TURN_KEY: ContextVar[str | None] = ContextVar("research_turn_key", default=None)
TURN_KEY_CONTEXT = "research_turn_key"

#: Words that do not change what a search looks for.
_STOPWORDS = frozenset("a an the of in on at for by with and or is are was were be who whom whose what which about info information details detail please find search look up lookup me tell more".split())


def query_terms(query: str) -> str:
    """A search's normalised terms: case, accents, punctuation and filler
    words ignored. "Who is Jane Roe?" and "jane roe" are the same search.
    Word order counts for a short query ("new york to boston" is not
    "boston to new york"); a longer one is compared as a set of terms."""
    text = unicodedata.normalize("NFKD", query or "").encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z0-9]+", text)
    kept = [w for w in words if w not in _STOPWORDS] or words
    if len(kept) <= SHORT_QUERY_WORDS:
        return " ".join(kept)
    return " ".join(sorted(set(kept)))


#: Up to this many terms, a query's word order counts.
SHORT_QUERY_WORDS = 4


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
    #: When this run's first LOOKUP was made (None: none yet). The research
    #: clock is lookup time: a long coding or writing turn that looks
    #: something up late is not out of research time.
    started: float | None = None
    searches: int = 0
    fetches: set[str] = field(default_factory=set)
    #: Sites (hosts) of the pages fetched in this turn.
    fetched_hosts: set[str] = field(default_factory=set)
    research: int = 0
    #: (tool, normalised terms) -> the query as first asked
    queries: dict[str, str] = field(default_factory=dict)
    #: A subagent call's floor (searches, fetches) it may make even when the
    #: turn's budget is spent (parallel research is not squeezed out).
    floor: tuple[int, int] = (0, 0)
    budget_refusals: int = 0
    refusals: int = 0
    #: Why tool calls ended for this turn ("search budget", "research time", ...), or "".
    stopped: str = ""

    def elapsed(self, now: float) -> float:
        return 0.0 if self.started is None else max(0.0, now - self.started)


#: Reservation outcomes.
OK = "ok"
OVER_SEARCHES = "search"
OVER_FETCHES = "fetch"
OVER_RESEARCH = "research"
OUT_OF_TIME = "time"
REPEAT = "repeat"
STOPPED = "stopped"
#: The last fetch is kept for a second site: every page so far is from one.
SECOND_SITE = "second_site"


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
        with self._lock:
            ledger = self._by_thread.get(thread_id)
            if ledger is None or ledger.turn_key != turn_key:
                ledger = TurnLedger(thread_id=thread_id, turn_key=turn_key, caps=caps, run_id=run_id)
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
                    ledger.started = None
                    ledger.stopped = ""
                    ledger.budget_refusals = 0
                    ledger.refusals = 0
            return ledger

    def current(self, thread_id: str) -> TurnLedger | None:
        with self._lock:
            return self._by_thread.get(thread_id)

    def reserve(self, ledger: TurnLedger, name: str, args: dict, *, extra: TurnLedger | None = None) -> tuple[str, str]:
        """Check and count one lookup, atomically. Returns (outcome, detail).
        `extra`: a subagent call's own ledger, which the call must also fit;
        within its floor the turn's caps (not its stop or repeats) are waived."""
        if name not in LOOKUP_TOOLS:
            return OK, ""
        now = self._clock()
        with self._lock:
            ledgers = [ledger] + ([extra] if extra is not None else [])
            within_floor = extra is not None and _within_floor(extra, name)
            for one in ledgers:
                if one.started is None:
                    one.started = now  # the research clock starts at the first lookup
            for one in ledgers:
                outcome = self._check(one, name, args, now, caps=not (within_floor and one is ledger))
                if outcome[0] != OK:
                    self._refused(ledgers, outcome[0])
                    return outcome
            for one in ledgers:
                self._count(one, name, args)
            return OK, ""

    def _check(self, ledger: TurnLedger, name: str, args: dict, now: float, *, caps: bool = True) -> tuple[str, str]:
        if name not in LOOKUP_TOOLS:
            return OK, ""
        if ledger.stopped:
            return STOPPED, ledger.stopped
        if name in SEARCH_TOOLS:
            key = _repeat_key(name, args)
            if key and key in ledger.queries:
                return REPEAT, ledger.queries[key]
        if not caps:
            return OK, ""
        if ledger.elapsed(now) >= ledger.caps.seconds:
            return OUT_OF_TIME, str(int(ledger.caps.seconds))
        if name in SEARCH_TOOLS:
            if ledger.searches >= ledger.caps.searches:
                return OVER_SEARCHES, str(ledger.caps.searches)
        if name in FETCH_TOOLS:
            url = _url_key(args)
            if url not in ledger.fetches and len(ledger.fetches) >= ledger.caps.fetches:
                return OVER_FETCHES, str(ledger.caps.fetches)
            # Web claims need two independent sources: when every page so far
            # is from one site, the last fetch is kept for another site
            # (real eval T02: six react.dev pages and no second site).
            host = url_host(url)
            if url not in ledger.fetches and ledger.caps.fetches >= 2 and len(ledger.fetches) >= ledger.caps.fetches - 1 and ledger.fetched_hosts == {host}:
                return SECOND_SITE, host
        if name in RESEARCH_TOOLS and ledger.research >= ledger.caps.research:
            return OVER_RESEARCH, str(ledger.caps.research)
        return OK, ""

    @staticmethod
    def _count(ledger: TurnLedger, name: str, args: dict) -> None:
        if name in SEARCH_TOOLS:
            ledger.searches += 1
            key = _repeat_key(name, args)
            if key:
                ledger.queries.setdefault(key, str((args or {}).get("query") or ""))
        elif name in FETCH_TOOLS:
            ledger.fetches.add(_url_key(args))
            if url_host(_url_key(args)):
                ledger.fetched_hosts.add(url_host(_url_key(args)))
        elif name in RESEARCH_TOOLS:
            ledger.research += 1

    @staticmethod
    def _refused(ledgers: list[TurnLedger], outcome: str) -> None:
        # A repeat is answered, not a sign the budget is spent: it never
        # counts toward the stop.
        for one in ledgers:
            one.refusals += 1
            if outcome not in (REPEAT, STOPPED, SECOND_SITE):
                one.budget_refusals += 1

    def release(self, ledger: TurnLedger, name: str, args: dict) -> None:
        """Give back a reservation whose call did not run as a lookup (a
        card, a refusal by the policy layer, an error)."""
        with self._lock:
            if name in SEARCH_TOOLS and ledger.searches > 0:
                ledger.searches -= 1
                key = _repeat_key(name, args)
                if ledger.queries.get(key) == str((args or {}).get("query") or ""):
                    ledger.queries.pop(key, None)
            elif name in FETCH_TOOLS:
                ledger.fetches.discard(_url_key(args))
            elif name in RESEARCH_TOOLS and ledger.research > 0:
                ledger.research -= 1

    def stop(self, ledger: TurnLedger, why: str) -> None:
        with self._lock:
            ledger.stopped = ledger.stopped or why


def url_host(url: str) -> str:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def sites_note(ledger: TurnLedger | None) -> str:
    """A note when the turn's pages all come from one site: the answer's web
    claims need a second, independent source."""
    if ledger is None or len(ledger.fetched_hosts) != 1:
        return ""
    (host,) = tuple(ledger.fetched_hosts)
    return f" Your fetched pages all come from one site ({host}): cite a second, independent site too (a link from another site in your search results counts)."


def _repeat_key(name: str, args: Any) -> str:
    """Repeats are per tool: an image search is not a web search."""
    terms = query_terms(str((args or {}).get("query") or "")) if isinstance(args, dict) else ""
    return f"{name}:{terms}" if terms else ""


def _within_floor(own: TurnLedger, name: str) -> bool:
    searches, fetches = own.floor
    if name in SEARCH_TOOLS:
        return own.searches < searches
    if name in FETCH_TOOLS:
        return len(own.fetches) < fetches
    return False


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
