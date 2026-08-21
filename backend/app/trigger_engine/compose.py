"""How a proactive message reads (FR-004, Article X).

The assistant is speaking first here, which changes the standard. A reply the
user asked for can afford to be terse; a message that arrives unbidden has to
justify its own interruption in its first clause, or it trains the user to
ignore the next one.

Two rules carried from Feature 001, because the same honesty applies whether
the assistant was asked or not:

  * anything INFERRED leads with its hedge — "looks like it's waiting on you",
    never "it is waiting for your input"
  * anything OBSERVED is stated plainly, without a hedge, because hedging a
    fact is its own dishonesty
"""

from __future__ import annotations

from string import Formatter

from .models import Rule, TriggerEvent


class _Missing(dict):
    """Renders an absent field as an explicit gap rather than a crash.

    Templates are validated at load (config.AVAILABLE_FIELDS), so this is a
    belt-and-braces path. When it fires, the gap is visible in the output
    instead of the message silently reading as though the field were empty.
    """

    def __missing__(self, key: str) -> str:
        return f"<{key} unavailable>"


def render_prompt(rule: Rule, event: TriggerEvent) -> str:
    """The prompt injected as the synthetic user turn."""
    fields = _Missing(event.fields)
    return Formatter().vformat(rule.prompt, (), fields)


def compose_proactive(rule: Rule, event: TriggerEvent, reply: str) -> str:
    """The message actually delivered.

    The agent's reply is the substance; this frames it so the user knows why
    their phone buzzed without having to infer it.
    """
    reply = (reply or "").strip()
    project = str(event.fields.get("project") or "").strip()

    if event.type.value == "watcher":
        state = str(event.fields.get("state") or "")
        if state == "waiting-on-user":
            # INFERRED (Feature 001 R2b: nothing in the record distinguishes a
            # permission prompt from a pause). The hedge leads.
            head = f"{project} looks like it's waiting on you" if project else "A session looks like it's waiting on you"
        elif state == "failed":
            head = f"{project} failed" if project else "A session failed"
        else:
            head = f"{project}" if project else "A session"
        return f"{head}.\n\n{reply}" if reply else f"{head}."

    return reply or "(the assistant returned nothing)"
