"""Loading the user-owned classification rules (FR-007, FR-008, FR-037).

Two behaviours here are load-bearing and easy to mistake for pedantry.

REJECT AT LOAD, DO NOT IGNORE AT MATCH TIME. A lowering exception is refused
when the file is read, naming file and line, rather than being silently skipped
when a call is classified. Ignoring produces correct behaviour and no
understanding:

    A file that silently does something safer than what its author wrote is a
    file whose author never learns they were wrong.

The user keeps a rule they believe is in force, is not, and writes more like it.
Failing the reload teaches; ignoring does not. The safe outcome is not
sufficient — the author has to find out.

A BROKEN FILE MAKES EVERYTHING TIER 3. Not "no rules", which would leave every
tool unclassified and — through FR-009 — Tier 3 anyway, but by accident rather
than by decision. `RuleSet.unreadable` records that it happened so the state is
inspectable instead of merely safe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .models import ClassificationRule, RuleException, Tier

logger = logging.getLogger(__name__)


class PolicyConfigError(ValueError):
    """Raised at LOAD time. Carries file and line so the author can find it."""


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[ClassificationRule, ...] = ()
    expires_after_seconds: int = 4 * 60 * 60
    #: Above this many resolved targets, confirming requires supplying the
    #: target count rather than a bare affirmation (FR-009).
    #:
    #: 10 IS A GUESS. It is not derived from usage, because there is none to
    #: derive it from: until Feature 004 the confirmation path had no completion
    #: route, so no distribution of target counts exists. It is set where a
    #: single "yes" stops feeling proportionate to the blast radius, and is
    #: expected to move once the surface has been used (Article X).
    threshold_targets: int = 10
    source_file: str = ""
    #: True when the file could not be read or parsed. Everything is Tier 3
    #: either way; this records WHY, so "no rules were written" and "the rules
    #: could not be read" are distinguishable.
    unreadable: bool = False
    error: str = ""


@dataclass
class ConfigLoader:
    """Hot-reloadable. A reload that fails validation KEEPS THE PREVIOUS RULES
    and says so — a config error must never silently widen what is permitted."""

    path: Path
    _last_good: RuleSet | None = field(default=None, repr=False)

    def load(self) -> RuleSet:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self._degrade("policy rules file not found", found=False)
        except OSError as exc:
            return self._degrade(f"policy rules unreadable: {exc}")

        try:
            doc = yaml.safe_load(raw) or {}
            ruleset = self._parse(doc)
        except PolicyConfigError as exc:
            # A rule the author got wrong. Loudly.
            return self._degrade(str(exc))
        except Exception as exc:  # noqa: BLE001 — a malformed file must not crash the gateway
            return self._degrade(f"policy rules malformed: {exc}")

        self._last_good = ruleset
        return ruleset

    def _degrade(self, message: str, *, found: bool = True) -> RuleSet:
        if self._last_good is not None:
            logger.error("%s — KEEPING PREVIOUS RULES (%d active)", message, len(self._last_good.rules))
            return self._last_good
        if found:
            logger.error("%s — no previous rules to keep; EVERY tool is Tier 3", message)
        else:
            logger.warning("%s — every tool is Tier 3 until rules are written (FR-009)", message)
        return RuleSet(source_file=str(self.path), unreadable=True, error=message)

    def _parse(self, doc: dict) -> RuleSet:
        policy = doc.get("policy") or {}
        raw_rules = policy.get("rules") or []
        rules: list[ClassificationRule] = []

        for index, raw in enumerate(raw_rules):
            if not isinstance(raw, dict):
                raise PolicyConfigError(f"{self.path}: rules[{index}] is not a mapping")
            pattern = raw.get("pattern")
            if not pattern:
                raise PolicyConfigError(f"{self.path}: rules[{index}] has no pattern")
            tier = self._tier(raw.get("tier"), f"rules[{index}]")

            exceptions: list[RuleException] = []
            for exception_index, raw_exception in enumerate(raw.get("exceptions") or []):
                where = f"rules[{index}].exceptions[{exception_index}]"
                if not isinstance(raw_exception, dict):
                    raise PolicyConfigError(f"{self.path}: {where} is not a mapping")
                exception_tier = self._tier(raw_exception.get("tier"), where)
                if exception_tier <= tier:
                    # FR-037. Refused here, not skipped later.
                    raise PolicyConfigError(
                        f"{self.path}: {where} would set {exception_tier.label} on a "
                        f'{tier.label} rule (pattern "{pattern}"). An exception may only RAISE a '
                        f"tier, never lower it. To make this call safer than the rule's default, "
                        f"change the rule's tier — that is a visible edit, where a narrow exception is not."
                    )
                exceptions.append(RuleException(when=raw_exception.get("when") or {}, tier=exception_tier))

            rules.append(ClassificationRule(pattern=pattern, tier=tier, exceptions=tuple(exceptions), source_file=str(self.path), source_line=index))

        confirmation = policy.get("confirmation") or {}
        return RuleSet(
            rules=tuple(rules),
            expires_after_seconds=int(confirmation.get("expires_after_seconds", 4 * 60 * 60)),
            threshold_targets=int(confirmation.get("threshold_targets", 10)),
            source_file=str(self.path),
        )

    def _tier(self, value, where: str) -> Tier:
        try:
            return Tier(int(value))
        except (TypeError, ValueError):
            raise PolicyConfigError(f"{self.path}: {where} has tier {value!r}; expected 1, 2 or 3") from None
