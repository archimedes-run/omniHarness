"""Memory off in a chat (live chat 2026-11-14: "What can you do for me, do not
reference my past chats and history with you" was answered from memory).

The owner's memory reached the model as a <memory> block in the system prompt
of every run, and nothing a person said in the chat could remove it: the
prompt told the model to read memory freely and gave no rule for a person
asking it not to. Prompt rules alone cannot guarantee it; the server applies
the switch:

- the run's server-owned context key MEMORY_OFF_KEY (set by the gateway from
  the chat's stored switch, which the owner's own message can turn on with one
  of a small closed set of phrasings, or the composer toggle) removes the
  memory block from the prompt and turns memory writes off for the run;
- every other run still gets the rule that memory is background.
"""

from __future__ import annotations

import re
from typing import Any

#: Server-owned run context key (app.gateway.services.SERVER_OWNED_RUN_KEYS).
MEMORY_OFF_KEY = "memory_off"

_NEG = r"(?:do\s*n[o']?t|don't|dont|never|please\s+don't|please\s+do\s+not|stop|without|no\s+need\s+to|avoid)"
_VERB = r"(?:use|using|reference|referencing|refer\s+to|referring\s+to|mention|mentioning|bring\s+up|look\s+at|rely\s+on|draw\s+on|consider|access|read)"
_WHAT = (
    r"(?:(?:my|our|any|the)\s+)?(?:(?:past|previous|prior|earlier|old|other)\s+(?:chats?|conversations?|sessions?|threads?|history)"
    r"|(?:chat|conversation)\s+history|history(?:\s+with\s+you)?|memory|memories|what\s+you\s+(?:know|remember)\s+about\s+me"
    r"|(?:anything|stuff)\s+you\s+(?:know|remember)\s+about\s+me|my\s+profile)"
)

#: The closed set of phrasings that turn memory off for the chat. Kept small on
#: purpose: a false positive only switches memory off (the owner sees the chip
#: and can switch it back on); it never adds anything to the prompt.
PHRASES: tuple[re.Pattern[str], ...] = (
    re.compile(rf"\b{_NEG}\s+(?:\w+\s+){{0,2}}?{_VERB}\s+(?:\w+\s+){{0,3}}?{_WHAT}\b", re.IGNORECASE),
    re.compile(r"\b(?:forget|ignore)\s+(?:everything\s+|all\s+|what\s+)?(?:you\s+know\s+about\s+me|my\s+(?:past\s+|previous\s+)?(?:chats?|history|memory)|(?:our|my)\s+(?:past|previous)\s+(?:chats?|conversations?))\b", re.IGNORECASE),
    re.compile(r"\b(?:treat\s+(?:me|this)\s+(?:as|like)\s+(?:a\s+)?(?:new|fresh|first)|start\s+(?:fresh|from\s+scratch)\s+without\s+(?:my\s+)?(?:history|memory))\b", re.IGNORECASE),
    re.compile(r"\b(?:memory|memories)\s+off\b|\bturn\s+off\s+(?:your\s+|the\s+)?memory\b|\bno\s+memory\b", re.IGNORECASE),
)


def asks_memory_off(text: str) -> bool:
    """Whether the person's own message asks not to use past chats, history or memory."""
    if not text or not text.strip():
        return False
    return any(p.search(text) for p in PHRASES)


def memory_off(context: Any) -> bool:
    """Whether this run's (server-owned) context says memory is off."""
    return isinstance(context, dict) and context.get(MEMORY_OFF_KEY) is True


#: In the prompt INSTEAD of the memory block when memory is off in the chat.
MEMORY_OFF_SECTION = """<memory_off>
Memory is OFF in this chat (the person asked for it). You have no memory of the person and their past chats here.
Do not use or mention anything about the person from earlier chats, saved memory, past drafts, the ledger, mail,
calendar or connected accounts unless they ask for it in this chat. When asked what you can do, describe your
capabilities in general terms (research with sources, writing, files and code, planning, connected apps once they
are switched on), not the person's own projects or plans.
</memory_off>
"""

#: Inside every memory block: memory is background, never volunteered against the person's wish.
MEMORY_RULE = (
    "Memory is background about the person, from earlier chats. Use it only where it helps the current request; do not "
    "volunteer it. If the person asks you not to use or reference their past chats, history or memory, do not use or "
    "mention any of it in your reply."
)
