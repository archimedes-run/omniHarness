"""Does the owner's request say what a NEW agent, skill or automation is FOR? (Spec 010)

Live, filler passed for a purpose ("please create me an agent thanks",
"create an agent called Bob", "crea un agente") and the model invented one.
So only the part of the request that can carry a purpose is judged:

- English, with a build noun (agent, skill, automation, bot, assistant, ...):
  the clause AFTER the noun ("create me an agent <that triages my inbox>"), or
  a compound noun right BEFORE it ("a <twitter> bot"), once politeness and
  filler are gone. A naming clause ("called Bob", "named Scout") gives a NAME,
  not a purpose: it is kept, and the owner is still asked.
- English without a build noun (a card answer such as "Triage my inbox"): any
  content word.
- Any other language: at least 3 content words once the build words of a few
  common languages are removed; a script written without spaces counts two
  characters as a word.
"""

from __future__ import annotations

import re
import unicodedata

#: What the builder makes.
NOUNS = frozenset("agent agents skill skills automation automations bot bots assistant assistants helper helpers workflow workflows something one thing".split())
#: Politeness, filler and the words of a bare build request: never a purpose.
FILLER = frozenset(
    "a an the me my i i'd i'm we us our you your please pls kindly thanks thank thx cheers can could would will shall just new another ones some "
    "quick simple basic small little create make build set setup up add start get give want need like do it this that there here now asap ok okay "
    "help hi hey for to with so yes sure".split()
)
#: English function words: a request that has one is read as English.
ENGLISH = frozenset("my the for to that which who of a an and me i in on every with it is are from about please".split())
#: Words that start a purpose clause after the noun.
MARKERS = frozenset("that to for which who whose so".split())
#: Build words of other common languages (verbs, nouns, articles, politeness).
OTHER_GENERIC = frozenset(
    # Spanish / Portuguese / Italian
    "crea crear creame créame hazme haz construye un una uno el la los las agente agentes asistente bot por favor gracias nuevo nueva mi me "
    "cria criar faz faça um uma o os novo obrigado obrigada crei creami fammi nuova grazie "
    # French
    "crée créer créez fais faites moi un une le la les agent agents assistant nouveau nouvelle mon ma merci s'il plaît svp "
    # German
    "erstelle erstellen erstell mach mache bau baue mir einen ein eine einem neuen neue neues agent agenten assistenten bitte danke mein meine "
    # Hindi
    "एक एजेंट बनाओ बनाइए बना दो मेरे लिए कृपया धन्यवाद "
    # Russian
    "создай создайте сделай агента агент бота мне пожалуйста спасибо нового новый "
    # Arabic
    "أنشئ اصنع وكيلا وكيل لي من فضلك شكرا".split()
)
#: Build words in scripts written without spaces (removed as substrings).
CJK_GENERIC = ("エージェント", "作って", "作成して", "作成", "作る", "ください", "を", "智能体", "代理", "创建", "一个", "帮我", "请", "에이전트", "만들어", "줘", "주세요")
_NO_SPACE_SCRIPT = re.compile(r"[぀-ヿ㐀-鿿가-힯฀-๿]")
_NAMING = frozenset({"called", "named", "name"})


def tokens(text: str) -> list[str]:
    """Words of any script: NFKC, casefolded, split on anything that is not a
    letter or a digit (an apostrophe stays inside a word)."""
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    cleaned = "".join(ch if ch.isalnum() or ch == "'" else " " for ch in folded)
    return [w.strip("'") for w in cleaned.split() if w.strip("'")]


def _drop_naming(words: list[str]) -> tuple[list[str], str | None]:
    """The words without a naming clause ("called Bob"), and the name."""
    for i, word in enumerate(words):
        if word in _NAMING and i + 1 < len(words):
            j = i + 1
            name = []
            while j < len(words) and words[j] not in MARKERS:
                name.append(words[j])
                j += 1
            return words[:i] + words[j:], " ".join(name) or None
    return words, None


def _generic(word: str) -> bool:
    return word in FILLER or word in NOUNS or word in OTHER_GENERIC


def _content(words: list[str]) -> list[str]:
    return [w for w in words if not _generic(w)]


def states_purpose(text: str) -> tuple[bool, str | None]:
    """(the text says what it is for, a name it gives the thing or None)."""
    words = tokens(text)
    if not words:
        return False, None
    noun_at = next((i for i, w in enumerate(words) if w in NOUNS and w not in ("one", "thing")), None)
    if noun_at is None:
        noun_at = next((i for i, w in enumerate(words) if w in ("something", "one", "thing")), None)
    if noun_at is not None:
        before, after = words[:noun_at], words[noun_at + 1 :]
        compound = []
        for word in reversed(before):
            if _generic(word):
                break
            compound.append(word)
        after, name = _drop_naming(after)
        return bool(compound or _content(after)), name
    words, name = _drop_naming(words)
    if any(w in ENGLISH for w in words) and all(w.isascii() for w in words):
        return bool(_content(words)), name
    return _foreign_purpose(text, words), name


def _foreign_purpose(text: str, words: list[str]) -> bool:
    """At least 3 content words outside the build words of common languages."""
    count = 0.0
    for word in words:
        if word in OTHER_GENERIC or word in FILLER or word in NOUNS:
            continue
        if _NO_SPACE_SCRIPT.search(word):
            for generic in CJK_GENERIC:
                word = word.replace(generic, " ")
            count += len(word.replace(" ", "")) / 2
        else:
            count += 1
    return count >= 3
