"""The chat builder's gateway side (Spec 010, Slice 2): drafts, live reads, diffs and saves.

Registered at startup as the harness's BuilderController
(omniharness.runtime.builder.controller), so the builder tools exist only in
the gateway. Every write goes through the ONE versioned store
(omniharness.config.config_versions for agents and skills;
app.gateway.routers.automations.edit_rules / undo_rule for automations), with
the base version the card was built on (stale: refused, FR-017), source
"chat", and the chat and card it came from (FR-018).

THREE GUARDS, each enforced HERE whatever the policy layer did, because a
rules file can be replaced and a tool can be reached in ways a list cannot
foresee:

1. WHERE: only the assistant in the owner's own chat
   (omniharness.runtime.builder.surface.builder_refusal). A scheduled,
   delegated, resumed, @-called or custom agent's run is refused, Tier 1
   reads included.
2. WHAT: never the proposing agent or anything in its call chain
   (surface.forbidden_targets, FR-030), by any path; in the bootstrap flow,
   only the agent being set up.
3. HOW: a save, grant or undo runs only as the confirmed action of its own
   card (app.policy.surface_run.confirming_action): never called directly,
   never under a rule that let it through without asking. A grant only when
   that confirmation was the card's button (FR-016).

WHAT THE MODEL READS BACK. `builder_read` and `builder_diff` return stored
text (instructions, skill files, rule prompts), so their results count as
content the turn read: a save proposed after them is a suggestion, saved only
by its button. Everything else the builder returns to the model (a draft's
acknowledgement, a card's plan, a save's result) names only ids, field names,
counts and versions, never stored text; the full draft or diff is shown to
the owner on the card. A draft also records what caused it, so a draft made
in a turn that read content stays a suggestion when it is saved later.

ACCESS NEVER RIDES ALONG. A save or an undo never widens what an agent may
use: its tool groups, per-tool list, the tools its skills allow, and its
standing grants. A widening is left out of the save and proposed separately
with builder_grant (button only); narrowing may ride. An automation that runs
as an agent holding standing grants is confirmed by button only, and its card
names that agent and those grants.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from app.gateway.builder import drafts
from app.gateway.builder.render import render_draft, render_live
from omniharness.config import config_versions
from omniharness.runtime.builder.surface import LEAD_AGENT, bootstrap_target, builder_refusal, forbidden_targets

logger = logging.getLogger(__name__)

KINDS = ("agent", "skill", "automation")
SKILL_MD = "SKILL.md"
#: The agent fields a draft may set (tool access is builder_grant's).
AGENT_FIELDS = ("display_name", "description", "instructions", "skills", "tool_groups", "model")
ACCESS_FIELDS = ("integrations", "tools")
#: The parts of an agent's config that decide what it may use or do. Kept as
#: they are by an undo; widened only through builder_grant.
ACCESS_KEYS = (config_versions.TOOLS_KEY, "tool_groups", "skills", "model", config_versions.AUTONOMY_KEY)
#: The config a NEW agent is saved with before its access is confirmed: no
#: tool groups. It still has what every agent run gets (the core tools, the
#: in-process built-ins, and in an interactive chat the sources that chat has
#: selected); it has none of the tool groups or apps it asked for until the
#: permission card the save raises is confirmed with its button.
NEW_AGENT_ACCESS = {"tool_groups": [], "skills": []}
#: Fixed wording for refusals that reach the model: never free text taken
#: from stored config or written by a model (a scan's reason).
INVALID = {
    "agent": "the agent has no instructions yet (field: instructions).",
    "skill": "the skill's SKILL.md is not valid (fields: description, body).",
}
#: The context key the builder_draft tool passes the turn's messages under.
MESSAGES_KEY = "_builder_messages"
#: The builder tools whose rules must be in force for the builder to be offered.
BUILDER_TOOL_NAMES = ("builder_draft", "builder_read", "builder_diff", "builder_save", "builder_grant", "builder_undo")
MCP_HANDOFF = "MCP servers are not built in chat. Nothing was drafted. Tell the user to open MCP Studio (the MCP page, /workspace/mcp) and describe it there: {request}"
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


class BuilderRefused(Exception):
    """A builder call refused, with the reason in words."""


def _run_sync(coro) -> Any:
    """Run a coroutine from sync code that may be inside a running loop."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 — re-raised in the caller
            box["error"] = exc

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _not_done(lead: str, exc: Exception, confirmed: bool) -> str:
    """A builder write that did not happen. Once its card was confirmed this
    RAISES, so the action is recorded FAILED (the card shows it did not
    happen, and it is no receipt), as the ledger does
    (app.ledger.controller); before that, it is the tool's answer."""
    if confirmed:
        raise RuntimeError(f"{lead}: {exc}") from exc
    return f"{lead}: {exc}"


class GatewayBuilderController:
    """The BuilderController the gateway registers (app/gateway/deps.py)."""

    def __init__(self, app_config_getter) -> None:
        self._config = app_config_getter

    # -- who, where -----------------------------------------------------------

    @staticmethod
    def _who(context: dict) -> tuple[str, str]:
        """(user id, thread id) from the run's server-set context."""
        user_id, thread_id = context.get("user_id"), context.get("thread_id")
        if not user_id or not thread_id:
            raise BuilderRefused("the builder needs a chat and a signed-in owner, and this run has neither.")
        return str(user_id), str(thread_id)

    def _guard(self, context: dict) -> tuple[str, str]:
        refusal = builder_refusal(context)
        if refusal is not None:
            raise BuilderRefused(refusal)
        return self._who(context)

    @staticmethod
    def _check_target(context: dict, kind: str, name: str) -> None:
        if kind != "agent":
            if bootstrap_target(context) is not None:
                raise BuilderRefused("this setup conversation creates its one agent only.")
            return
        if name in forbidden_targets(context):
            if name == LEAD_AGENT:
                raise BuilderRefused("I cannot change my own instructions from chat. The owner can change them in Agent Studio.")
            raise BuilderRefused(f"an agent cannot change itself or an agent in its call chain ({name!r}).")
        allowed = bootstrap_target(context)
        if allowed is not None and name != allowed:
            raise BuilderRefused(f"this setup conversation creates {allowed!r} only.")

    # -- names and live state ---------------------------------------------------

    def _norm(self, context: dict, kind: str, name: str) -> str:
        name = (name or "").strip()
        if kind == "agent":
            if name.lower() == LEAD_AGENT or (bootstrap_target(context) == LEAD_AGENT and not name):
                return LEAD_AGENT
            from omniharness.config.agents_config import validate_agent_name

            try:
                return validate_agent_name(name.lower()) or ""
            except ValueError as exc:
                raise BuilderRefused(str(exc)) from exc
        if kind == "skill":
            try:
                return self._skills().validate_skill_name(name)
            except ValueError as exc:
                raise BuilderRefused(str(exc)) from exc
        if not name or len(name) > 120:
            raise BuilderRefused("an automation needs a rule id (1 to 120 characters).")
        return name

    def _skills(self):
        from omniharness.skills.storage import get_or_new_skill_storage

        return get_or_new_skill_storage(app_config=self._config())

    def _live(self, user_id: str, kind: str, name: str) -> tuple[dict | None, int]:
        """(snapshot, version) read from the store now."""
        if kind == "agent":
            snapshot, version = config_versions.current_agent_state(user_id, name)
            if name == LEAD_AGENT:
                from omniharness.config.agents_config import load_agent_soul

                snapshot = {"config": dict((snapshot or {}).get("config") or {}), "soul": (snapshot or {}).get("soul") or load_agent_soul(None) or ""}
            return snapshot, version
        if kind == "skill":
            storage = self._skills()
            if not storage.custom_skill_exists(name):
                if storage.public_skill_exists(name):
                    raise BuilderRefused(f"{name!r} is an installed skill, which is not edited from chat. Offer to make a custom copy under a new name.")
                return None, config_versions.skill_version(name, storage)
            # An existing custom skill is changed from chat only when its
            # recorded owner is this account (one without a recorded owner is
            # changed in Skill Studio).
            if config_versions.skill_owner(name, storage) != user_id:
                raise BuilderRefused(f"the skill {name!r} has no recorded owner matching this account; change it in Skill Studio.")
            history = config_versions.skill_history(name, storage)
            files = history[-1].snapshot if history and history[-1].snapshot is not None else {"files": {SKILL_MD: storage.read_custom_skill(name)}}
            return files, config_versions.skill_version(name, storage)
        self._automations_allowed()
        from app.gateway.automations_store import RulesEditError
        from app.gateway.routers.automations import rule_versions

        try:
            version, _, on_file = rule_versions(self._config(), name)
        except RulesEditError as exc:
            raise BuilderRefused("could not read the rules file.") from exc
        return on_file, version

    @staticmethod
    def _automations_allowed() -> None:
        from app.gateway.ownership import admits_additional_accounts

        # Automations are install-wide (the owner's). While the install admits
        # only its owner account, a signed-in person is the owner.
        if admits_additional_accounts():
            raise BuilderRefused("automations are changed only by the owner account, from the Automations page.")

    # -- composing a draft -------------------------------------------------------

    def _compose(self, user_id: str, kind: str, name: str, fields: dict, live: dict | None) -> tuple[dict, list[str], list[str]]:
        """(the proposed snapshot, dropped names, notes)."""
        if kind == "agent":
            return self._compose_agent(name, fields, live)
        if kind == "skill":
            return self._compose_skill(name, fields, live)
        return self._compose_rule(user_id, name, fields, live)

    def _compose_agent(self, name: str, fields: dict, live: dict | None) -> tuple[dict, list[str], list[str]]:
        cfg = self._config()
        config = dict((live or {}).get("config") or {})
        if name != LEAD_AGENT:
            config["name"] = name
        soul = (live or {}).get("soul") or ""
        dropped: list[str] = []
        notes: list[str] = []
        unknown = [key for key in fields if key not in AGENT_FIELDS and key not in ACCESS_FIELDS]
        if unknown:
            notes.append(f"Not part of an agent here, left out: {', '.join(sorted(unknown))}.")
        for key in ("display_name", "description"):
            if isinstance(fields.get(key), str):
                config[key] = fields[key].strip()[: 80 if key == "display_name" else 300]
        if isinstance(fields.get("instructions"), str):
            soul = fields["instructions"].strip()[:20_000]
        if "model" in fields:
            model = fields.get("model")
            if model and cfg.get_model_config(str(model)) is None:
                dropped.append(f"model {model!r}")
            elif model:
                config["model"] = str(model)
        if isinstance(fields.get("skills"), list):
            known = {s.name for s in self._skills().load_skills(enabled_only=True)}
            wanted = [s for s in fields["skills"] if isinstance(s, str)]
            dropped += [s for s in wanted if s not in known]
            config["skills"] = [s for s in dict.fromkeys(wanted) if s in known]
        if isinstance(fields.get("tool_groups"), list):
            known = {g.name for g in cfg.tool_groups}
            wanted = [g for g in fields["tool_groups"] if isinstance(g, str)]
            dropped += [g for g in wanted if g not in known]
            config["tool_groups"] = [g for g in dict.fromkeys(wanted) if g in known]
        return {"config": config, "soul": soul}, dropped, notes

    def _compose_skill(self, name: str, fields: dict, live: dict | None) -> tuple[dict, list[str], list[str]]:
        import yaml

        files = dict((live or {}).get("files") or {})
        meta, body = self._skill_meta(files.get(SKILL_MD, ""))
        description = str(meta.get("description") or "")
        if isinstance(fields.get("description"), str):
            description = fields["description"].strip()
        if isinstance(fields.get("body"), str):
            body = fields["body"].strip()
        notes = []
        unknown = [key for key in fields if key not in ("description", "body")]
        if unknown:
            notes.append(f"Not part of a skill here, left out: {', '.join(sorted(unknown))}.")
        # Every other frontmatter field (allowed-tools among them) is kept as
        # it is: a draft changes the description and the body only.
        meta = {**meta, "name": name, "description": description}
        files[SKILL_MD] = f"---\n{yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()}\n---\n\n{body}\n"
        return {"files": files}, [], notes

    @staticmethod
    def _skill_meta(text: str) -> tuple[dict, str]:
        """(frontmatter, body) of a SKILL.md."""
        import yaml

        match = _FRONTMATTER.match(text or "")
        if not match:
            return {}, ""
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        return (meta if isinstance(meta, dict) else {}), match.group(2).strip()

    def _compose_rule(self, user_id: str, name: str, fields: dict, live: dict | None) -> tuple[dict, list[str], list[str]]:
        rule = json.loads(json.dumps(live or {}))
        for key, value in fields.items():
            if key == "id":
                continue
            if key == "match" and isinstance(value, dict) and isinstance(rule.get("match"), dict):
                rule["match"] = {**rule["match"], **value}
            else:
                rule[key] = value
        rule["id"] = name
        rule.setdefault("type", "cron")
        rule.setdefault("enabled", True)
        return rule, [], []

    # -- access --------------------------------------------------------------------

    def _assembled_tools(self, user_id: str, config: dict) -> list:
        """The tools a run of an agent with this config is offered, assembled
        the way the run assembles them (lead_agent.agent): config tools by
        tool group or per-tool list, the in-process built-ins and core tools,
        MCP tools, view_image for a vision model, `task` (as with subagents
        on), `research` (bound in every mode), then filtered by the skills'
        allowed-tools. Built in a copied
        context: assembly resets per-request registries the running turn uses."""
        import contextvars

        def build() -> list:
            from omniharness.agents.lead_agent.agent import _load_enabled_skills_for_tool_policy, _resolve_model_name
            from omniharness.config.agents_config import AgentConfig
            from omniharness.mcp.cache import get_cached_mcp_tools
            from omniharness.skills.tool_policy import filter_tools_by_skill_allowed_tools
            from omniharness.tools import get_available_tools

            cfg = self._config()
            fields = {k: v for k, v in config.items() if k in AgentConfig.model_fields}
            agent = AgentConfig.model_validate({**fields, "name": str(config.get("name") or "draft")})
            model_name = _resolve_model_name(agent.model, app_config=cfg)
            tools = get_available_tools(model_name=model_name, groups=agent.tool_groups, subagent_enabled=True, app_config=cfg, user_id=user_id, tool_access=agent.tools, research_enabled=True)
            skills = _load_enabled_skills_for_tool_policy(set(agent.skills) if agent.skills is not None else None, app_config=cfg)
            dynamic = {t.name for t in (get_cached_mcp_tools() or [])}
            return filter_tools_by_skill_allowed_tools(tools, skills, always_include=dynamic)

        return contextvars.copy_context().run(build)

    def _effective_tools(self, user_id: str, config: dict) -> set[str]:
        return {t.name for t in self._assembled_tools(user_id, config)}

    def _split_access(self, user_id: str, before: dict | None, after: dict) -> tuple[dict, dict | None]:
        """(the config a save may write, the access it left out). A change that
        would let the agent use any tool it does not have now is left out
        (tool groups, then skills, then model) and returned to be proposed with
        builder_grant. Narrowing rides with the save."""
        base = dict(NEW_AGENT_ACCESS) if before is None else dict(before)
        had = self._effective_tools(user_id, base)
        wanted = self._effective_tools(user_id, after)
        if wanted <= had:
            return after, None
        applied = dict(after)
        left_out: dict = {}
        for key in ("tool_groups", "skills", "model"):
            if self._effective_tools(user_id, applied) <= had:
                break
            if applied.get(key) != base.get(key):
                left_out[key] = after.get(key)
                if key in base:
                    applied[key] = base[key]
                else:
                    applied.pop(key, None)
        left_out["adds"] = sorted(wanted - had)
        return applied, left_out

    def _widens(self, user_id: str, before: dict | None, after: dict) -> bool:
        base = dict(NEW_AGENT_ACCESS) if before is None else dict(before)
        return not self._effective_tools(user_id, after) <= self._effective_tools(user_id, base)

    def _integration_tools(self, user_id: str, integration: str) -> list[tuple[str, int | None]]:
        """(tool name, tier) of one integration's tools for this user, from the
        same assembly a run uses; tier from the policy classifier (None: no
        rule names it, so it is never offered)."""
        import contextvars

        from app.policy.explain import explain
        from app.policy.registration import shared_loader

        cfg = self._config()

        def names() -> list[str]:
            if integration.startswith("builtin:"):
                from omniharness.tools import get_available_tools
                from omniharness.tools.agent_access import integration_of

                groups = {c.name: c.group for c in cfg.tools if getattr(c, "group", None)}
                out = []
                for tool in get_available_tools(include_mcp=False, app_config=cfg, subagent_enabled=True):
                    try:
                        if integration_of(tool, config_groups=groups) == integration:
                            out.append(tool.name)
                    except LookupError:
                        continue
                return out
            if integration.startswith("local:"):
                from omniharness.mcp.cache import get_cached_mcp_tools

                prefix = f"{integration[6:]}_"
                return [t.name for t in get_cached_mcp_tools() or [] if t.name.startswith(prefix)]
            if integration.startswith("connector:"):
                from omniharness.tools.tools import assemble_connector_tools

                return [t.name for t in assemble_connector_tools(cfg, user_id, [integration[10:]])]
            return []

        ruleset = shared_loader(cfg.policy).load(notify=False)
        out = []
        for name in contextvars.copy_context().run(names):
            decision = explain(name, {}, ruleset)
            out.append((name, None if decision.refused else int(decision.tier)))
        return out

    def _runs_as(self, user_id: str, rule: dict) -> tuple[str, list[str], list[str]]:
        """(the agent a rule runs as, that agent's standing grants, the rule's
        own grant-like keys)."""
        from app.policy.grants import granted_classes

        agent = str(rule.get("agent") or "").strip().lower() or LEAD_AGENT
        try:
            grants = list(granted_classes(user_id, agent))
        except Exception:  # noqa: BLE001 — unreadable grants: treated as held (button only)
            grants = ["(could not be read)"]
        own = sorted(k for k in rule if "grant" in str(k).lower() or "autonomy" in str(k).lower())
        return agent, grants, own

    def _automation_card(self, user_id: str, rule: dict) -> tuple[str, str]:
        """(the card's line about who the automation runs as, why it is button
        only or "")."""
        agent, grants, own = self._runs_as(user_id, rule)
        who = "the assistant" if agent == LEAD_AGENT else f"the agent `{agent}`"
        line = f"Runs as {who}. " + (f"Standing grants it holds (done on its own when this runs): {', '.join(grants)}." if grants else "It holds no standing grants.")
        if own:
            line += f" The rule also carries: {', '.join(own)}."
        reason = "an automation that runs with standing grants" if grants or own else ""
        return line, reason

    # -- validation, shared by the card and the save --------------------------

    def _validate(self, user_id: str, draft: dict) -> None:
        kind, name, snapshot = draft["kind"], draft["name"], draft["snapshot"]
        if kind == "agent":
            if not (snapshot.get("soul") or "").strip():
                raise BuilderRefused(INVALID["agent"])
            return
        if kind == "skill":
            storage = self._skills()
            try:
                storage.validate_skill_markdown_content(name, snapshot["files"][SKILL_MD])
            except ValueError as exc:
                raise BuilderRefused(INVALID["skill"]) from exc
            return
        self._validate_rule(user_id, snapshot)

    def _validate_rule(self, user_id: str, rule: dict) -> None:
        from app.gateway.automations_store import RulesEditError, put_rule, read_rules, validate
        from app.gateway.trigger_engine_wiring import SUPPORTED_SOURCE_TYPES, _resolve_rules_path

        cfg = self._config().trigger_engine
        if not getattr(cfg, "rules_path", ""):
            raise BuilderRefused("no rules file is configured (trigger_engine.rules_path), so automations cannot be saved; set one in config.yaml first.")
        match = rule.get("match")
        schedule = match.get("schedule") if isinstance(match, dict) else None
        if rule.get("type") == "cron" and schedule and len(str(schedule).split()) != 5:
            raise BuilderRefused("the schedule is not a five-field cron expression (field: match.schedule).")
        agent = rule.get("agent")
        if isinstance(agent, str) and agent.strip().lower() not in ("", LEAD_AGENT):
            from omniharness.config.agents_config import load_agent_config

            try:
                load_agent_config(agent.strip().lower(), user_id=user_id)
            except (FileNotFoundError, ValueError) as exc:
                raise BuilderRefused("the agent the rule runs as does not exist (field: agent); a rule runs only as an agent that exists.") from exc
        try:
            current = read_rules(_resolve_rules_path(cfg)).doc
            validate(put_rule(current, rule["id"], rule), SUPPORTED_SOURCE_TYPES, current)
        except RulesEditError as exc:
            raise BuilderRefused("the automation engine would refuse the rule (fields: type, match, prompt, destination).") from exc
        except (OSError, ValueError) as exc:
            raise BuilderRefused("could not read the rules file.") from exc

    # -- the tools ---------------------------------------------------------------

    def draft(self, context: dict, *, kind: str, name: str, fields: dict[str, Any], guessed: list[str], replace_current: bool) -> str:
        try:
            user_id, thread_id = self._guard(context)
            if kind == "mcp_server":
                return MCP_HANDOFF.format(request=str((fields or {}).get("request") or name or "(what they described)")[:500])
            if kind not in KINDS:
                raise BuilderRefused(f"the builder makes agents, skills and automations, not {kind!r}.")
            if kind == "agent" and bootstrap_target(context) is not None:
                # The setup conversation writes its one agent, whatever the
                # model called it; that name becomes its display name.
                given = (name or "").strip()
                name = bootstrap_target(context) or LEAD_AGENT
                if given and given.lower() != name and not (fields or {}).get("display_name"):
                    fields = {**(fields or {}), "display_name": given}
            name = self._norm(context, kind, name)
            self._check_target(context, kind, name)
            current = drafts.active(user_id, thread_id)
            if current and (current.get("kind"), current.get("name")) != (kind, name) and not replace_current:
                return (
                    f"Nothing was drafted: this chat is already building the {current.get('kind')} `{current.get('name')}`. "
                    "Ask the user whether to drop that draft and start this one; if they agree, call builder_draft again with replace_current=true."
                )
            live, version = self._live(user_id, kind, name)
            snapshot, dropped, notes = self._compose(user_id, kind, name, dict(fields or {}), live)
            access_request = None
            if kind == "agent":
                applied, access_request = self._split_access(user_id, (live or {}).get("config") if live is not None else None, snapshot["config"])
                snapshot = {**snapshot, "config": applied}
                requested = {k: [v for v in fields.get(k) or [] if isinstance(v, str)] for k in ACCESS_FIELDS if (fields or {}).get(k)}
                if requested:
                    access_request = {**(access_request or {"adds": []}), **requested}
                if access_request:
                    notes.append("Tool access is not saved with this draft: " + self._access_words(access_request) + ". Once it is saved, a permission card asks for it; only that card's button confirms it.")
            origin, origin_source = self._turn_origin(context)
            draft = {
                "id": drafts.new_draft_id(),
                "kind": kind,
                "name": name,
                "title": self._title(kind, name, snapshot),
                "mode": "edit" if live is not None else "create",
                "base_version": version,
                "snapshot": snapshot,
                "guessed": [g for g in guessed if isinstance(g, str)],
                "notes": ([f"Left out (not found here): {', '.join(dropped)}."] if dropped else []) + notes,
                "access_request": access_request,
                "origin": origin,
                "origin_source": origin_source,
                "created_at": drafts.now(),
            }
            problem = None
            try:
                self._validate(user_id, draft)
            except BuilderRefused as exc:
                problem = str(exc)
            drafts.put_draft(user_id, thread_id, draft)
            nxt = f"Not ready to save: {problem} Revise it with builder_draft." if problem else f"To propose saving it, call builder_save with draft_id {draft['id']!r}."
            return f"{self._model_ack(draft, live)}\n\n{nxt}"
        except BuilderRefused as exc:
            return f"Nothing was drafted: {exc}"

    def _turn_origin(self, context: dict) -> tuple[str, str]:
        """What caused this turn's draft (app.policy.lineage), from the turn's
        messages the tool passed; unknown fails toward a suggestion."""
        from app.policy.lineage import initiation_origin
        from app.policy.provenance import is_synthetic_turn

        messages = context.get(MESSAGES_KEY)
        if not isinstance(messages, list):
            return "unknown", ""
        return initiation_origin(messages, synthetic=is_synthetic_turn(context))

    @staticmethod
    def _access_words(request: dict) -> str:
        """The access a draft asked for, in words (names and ids only)."""
        parts = []
        if "tool_groups" in request:
            parts.append(f"tool groups: {', '.join(request['tool_groups']) if isinstance(request['tool_groups'], list) else 'all'}")
        for key in ("integrations", "tools", "skills"):
            if isinstance(request.get(key), list):
                parts.append(f"{key}: {', '.join(request[key]) or '(none)'}")
        if request.get("model"):
            parts.append(f"model: {request['model']}")
        if request.get("adds"):
            parts.append(f"tools it would gain: {', '.join(request['adds'])}")
        return "; ".join(parts)

    @staticmethod
    def _model_ack(draft: dict, live: dict | None) -> str:
        """What the MODEL is told about a draft: ids, field names, counts and
        versions, never stored text (the owner reads the draft on its card)."""
        from app.gateway.builder.render import fields_of

        kind, name = draft["kind"], draft["name"]
        after = fields_of(kind, draft["snapshot"])
        if draft.get("mode") == "create":
            what = f"a new {kind} `{name}`; fields set: {', '.join(k for k, v in after.items() if v not in (None, '', [], {})) or 'none'}"
        else:
            before = fields_of(kind, live)
            changed = [k for k in dict.fromkeys([*before, *after]) if before.get(k) != after.get(k)]
            what = f"a change to the {kind} `{name}` (based on version {draft.get('base_version')}); fields changed: {', '.join(changed) or 'none'}"
        extra = []
        if draft.get("access_request"):
            extra.append("Tool access left out of the draft: once it is saved, a permission card asks for it (button only).")
        dropped = [n for n in draft.get("notes") or [] if n.startswith("Left out (not found here)") or n.startswith("Not part of")]
        extra += dropped
        tail = (" " + " ".join(extra)) if extra else ""
        return f"Draft `{draft['id']}` recorded in this chat (nothing saved): {what}. The user sees the full draft on its card.{tail}"

    @staticmethod
    def _title(kind: str, name: str, snapshot: dict) -> str:
        if kind == "agent":
            return str((snapshot.get("config") or {}).get("display_name") or name)
        return name

    def read(self, context: dict, *, kind: str, name: str | None) -> str:
        try:
            user_id, _ = self._guard(context)
            if kind not in KINDS:
                raise BuilderRefused(f"the builder reads agents, skills and automations, not {kind!r}.")
            if not name:
                return self._list(user_id, kind)
            name = self._norm(context, kind, name)
            live, version = self._live(user_id, kind, name)
            extra = self._schedules_of(name) if kind == "agent" and live is not None else []
            return render_live(kind, name, live, version, extra)
        except BuilderRefused as exc:
            return f"Could not read it: {exc}"

    def _list(self, user_id: str, kind: str) -> str:
        if kind == "agent":
            from omniharness.config.agents_config import list_custom_agents

            agents = list_custom_agents(user_id=user_id)
            return "Agents: " + (", ".join(f"{a.name} ({a.display_name or a.name}: {a.description or 'no description'})" for a in agents) or "(none yet)")
        if kind == "skill":
            skills = self._skills().load_skills(enabled_only=False)
            custom = [s for s in skills if str(getattr(s, "category", "")).endswith("custom")]
            return "Custom skills: " + (", ".join(f"{s.name} ({s.description})" for s in custom) or "(none yet)")
        self._automations_allowed()
        from app.gateway.automations_store import read_rules, rules_by_id
        from app.gateway.trigger_engine_wiring import _resolve_rules_path

        try:
            rules = rules_by_id(read_rules(_resolve_rules_path(self._config().trigger_engine)).doc)
        except (OSError, ValueError) as exc:
            raise BuilderRefused(f"could not read the rules file: {exc}") from exc
        return "Automations: " + (", ".join(f"{rid} ({r.get('type')}, {'on' if r.get('enabled', True) else 'off'}{', as ' + str(r['agent']) if r.get('agent') else ''})" for rid, r in rules.items()) or "(none yet)")

    def _schedules_of(self, agent: str) -> list[str]:
        try:
            from app.gateway.automations_store import read_rules, rules_by_id
            from app.gateway.trigger_engine_wiring import _resolve_rules_path

            rules = rules_by_id(read_rules(_resolve_rules_path(self._config().trigger_engine)).doc)
        except Exception:  # noqa: BLE001 — a read without schedules, not a failed read
            return []
        mine = [f"{rid}: {json.dumps(r.get('match'), ensure_ascii=False)}{'' if r.get('enabled', True) else ' (off)'}" for rid, r in rules.items() if str(r.get("agent") or "").lower() == agent]
        return [f"schedules (automations): {'; '.join(mine)}"] if mine else ["schedules (automations): (none)"]

    def diff(self, context: dict, *, draft_id: str) -> str:
        try:
            user_id, thread_id = self._guard(context)
            draft = drafts.get_draft(user_id, thread_id, draft_id)
            if draft is None:
                raise BuilderRefused(f"there is no draft {draft_id!r} in this chat.")
            live, version = self._live(user_id, draft["kind"], draft["name"])
            return render_draft(draft, live=live, live_version=version)
        except BuilderRefused as exc:
            return f"Could not build the diff: {exc}"

    # -- before the card -----------------------------------------------------------

    def precheck(self, tool_name: str, arguments: dict, context: dict) -> dict:
        """Before a builder card: {"refused", "note" (the owner's card text),
        "replaces", "arguments" (pinned), "origin" (a draft's own cause, which
        may only degrade the card's), "button_only" (why, or "")}."""
        out: dict = {"refused": None, "note": "", "replaces": False, "arguments": arguments, "origin": None, "button_only": ""}
        try:
            if tool_name == "builder_save":
                draft_id = str(arguments.get("draft_id") or "")
                if not draft_id:
                    # The chat's current draft, pinned on the card: the card
                    # saves exactly the draft it shows.
                    user_id, thread_id = self._guard(context)
                    draft_id = str((drafts.active(user_id, thread_id) or {}).get("draft_id") or "")
                draft, live, version = self._ready_draft(context, draft_id)
                note = render_draft(draft, live=live, live_version=version)
                if draft["kind"] == "automation":
                    line, why = self._automation_card(self._who(context)[0], draft["snapshot"])
                    note = f"{note}\n\n{line}"
                    out["button_only"] = why
                if draft.get("origin") not in (None, "user"):
                    out["origin"] = (draft["origin"], draft.get("origin_source") or "")
                out.update(note=note, replaces=True, arguments={**arguments, "draft_id": draft_id})
                return out
            if tool_name == "builder_grant":
                out["note"] = self._grant_plan(context, arguments)[0]
                return out
            if tool_name == "builder_undo":
                plan = self._undo_plan(context, arguments)
                out.update(note=plan["text"], button_only=plan["button_only"])
                return out
            out["refused"] = f"{tool_name} is not a builder proposal."
            return out
        except BuilderRefused as exc:
            out["refused"] = str(exc)
            return out

    def unavailable_reason(self) -> str | None:
        """Why the builder is not offered on this install, or None. Its saves
        need the policy layer's cards, and an install's own rules file must
        name every builder tool (an unruled tool is never offered)."""
        try:
            from app.policy.coverage import has_rule
            from app.policy.registration import shared_loader

            policy = getattr(self._config(), "policy", None)
            if policy is None or not getattr(policy, "enabled", True):
                return "the permission policy is off, so nothing could be confirmed on a card."
            ruleset = shared_loader(policy).load(notify=False)
            missing = [n for n in BUILDER_TOOL_NAMES if not has_rule(n, ruleset)]
        except Exception as exc:  # noqa: BLE001 — not knowing is not offering
            return f"the policy rules could not be read ({type(exc).__name__})."
        if missing:
            return f"the policy rules file in force has no rule for: {', '.join(missing)} (copy them from the shipped default_rules.yaml)."
        return None

    def _ready_draft(self, context: dict, draft_id: str) -> tuple[dict, dict | None, int]:
        """The draft, if it may be saved now: this chat's, the active one, not
        dropped, an allowed target, valid, and based on the current version."""
        user_id, thread_id = self._guard(context)
        draft = drafts.get_draft(user_id, thread_id, draft_id) if draft_id else None
        if draft is None:
            raise BuilderRefused(f"there is no draft {draft_id!r} in this chat." if draft_id else "this chat has no draft to save; draft it with builder_draft first.")
        current = drafts.active(user_id, thread_id)
        if draft.get("dropped") or current is None or current.get("draft_id") != draft_id:
            raise BuilderRefused("that draft was dropped or replaced by a newer one; save the current draft instead.")
        if draft.get("saved_version") is not None:
            raise BuilderRefused(f"that draft was already saved (version {draft['saved_version']}).")
        self._check_target(context, draft["kind"], draft["name"])
        live, version = self._live(user_id, draft["kind"], draft["name"])
        if version != draft.get("base_version") or (live is None) != (draft.get("mode") == "create"):
            raise BuilderRefused(f"the {draft['kind']} {draft['name']!r} changed since this draft was made (it was version {draft.get('base_version')}, it is now version {version}). Draft it again on the current version.")
        self._validate(user_id, draft)
        if draft["kind"] == "agent" and self._widens(user_id, (live or {}).get("config") if live is not None else None, draft["snapshot"].get("config") or {}):
            raise BuilderRefused("this draft would widen the agent's tool access; draft it again (access is proposed separately with builder_grant).")
        return draft, live, version

    # -- after the card: the writes ---------------------------------------------

    @staticmethod
    def _confirmed(tool_name: str, arguments: dict, *, button: bool = False):
        """The confirmed action of THIS call's own card, or refused."""
        from app.policy.surface_run import confirming_action
        from omniharness.agents.tool_surface import LEAD

        action = confirming_action()
        if action is None or action.tool_name != tool_name or any(action.arguments.get(k) != v for k, v in arguments.items()):
            raise BuilderRefused("a builder change is made only from its confirmed card, and this one was not confirmed.")
        if action.delegation_chain or action.run_markers or (action.surface or {}).get("kind", LEAD) != LEAD:
            raise BuilderRefused("a builder change is made only from the owner's own chat with the assistant.")
        if (button or getattr(action, "button_only_reason", "")) and (action.confirmation or {}).get("via") != "button":
            raise BuilderRefused("tool access and standing grants are confirmed only with the card's button; nothing was changed.")
        return action

    def save(self, context: dict, *, draft_id: str) -> str:
        try:
            confirmed = False
            action = self._confirmed("builder_save", {"draft_id": draft_id})
            confirmed = True
            user_id, thread_id = self._who(context)
            draft, live, version = self._ready_draft(context, draft_id)
            extra = {"via": "chat", "thread_id": thread_id, "card_id": action.id}
            who = f"user:{user_id}"
            kind, name = draft["kind"], draft["name"]
            if kind == "agent":
                snapshot = json.loads(json.dumps(draft["snapshot"]))
                # Tool access stays exactly as it is now: widening it is
                # builder_grant's, by button (FR-016).
                cfg = snapshot.setdefault("config", {})
                current_tools = ((live or {}).get("config") or {}).get(config_versions.TOOLS_KEY)
                if current_tools is None:
                    cfg.pop(config_versions.TOOLS_KEY, None)
                else:
                    cfg[config_versions.TOOLS_KEY] = current_tools
                made = config_versions.write_agent(user_id, name, snapshot, who=who, source="chat", base_version=version, extra=extra)
                new_version = made.version
            elif kind == "skill":
                new_version = self._save_skill(user_id, name, draft, live, version, who, extra)
            else:
                new_version = self._save_rule(name, draft, version, who)
            drafts.mark_saved(user_id, thread_id, draft_id, new_version)
            permission = self._propose_access(context, action, name, draft["access_request"]) if kind == "agent" and draft.get("access_request") else None
            logger.info("builder: saved %s %r as version %s (thread %s, card %s)", kind, name, new_version, thread_id, action.id)
            verb = "Created" if draft.get("mode") == "create" else "Saved"
            later = ""
            if permission:
                later = (
                    f" It has none of the access it asked for until the user confirms its permission card (action `{permission}`, button only);"
                    " until then it has only what every agent run gets (the core and built-in tools, and in a chat the apps that chat has selected)."
                )
            elif draft.get("access_request"):
                later = " The access it asked for was left out; propose it with builder_grant (button only)."
            return f"{verb} the {kind} `{name}` as version {new_version} (source: chat). To undo it, propose builder_undo with version {new_version}.{later}"
        except (config_versions.StaleWriteError, BuilderRefused) as exc:
            return _not_done("Nothing was saved", exc, confirmed)

    def _save_skill(self, user_id: str, name: str, draft: dict, live: dict | None, version: int, who: str, extra: dict) -> int:
        from omniharness.skills.security_scanner import scan_skill_content

        storage = self._skills()
        content = draft["snapshot"]["files"][SKILL_MD]
        scan = _run_sync(scan_skill_content(content, executable=False, location=f"{name}/{SKILL_MD}", app_config=self._config()))
        if scan.decision == "block":
            raise BuilderRefused("the security scan blocked the skill; change its body and draft it again.")
        record = {
            **extra,
            "action": "create" if live is None else "edit",
            "author": "human",
            "file_path": SKILL_MD,
            "prev_content": ((live or {}).get("files") or {}).get(SKILL_MD),
            "new_content": content,
            "scanner": {"decision": scan.decision, "reason": scan.reason},
        }
        made = config_versions.write_skill(name, {SKILL_MD: content}, who=who, source="chat", base_version=version, extra=record, storage=storage, owner_id=user_id)
        from omniharness.agents.lead_agent.prompt import refresh_skills_system_prompt_cache_async

        _run_sync(refresh_skills_system_prompt_cache_async())
        return made.version

    def _save_rule(self, name: str, draft: dict, version: int, who: str) -> int:
        from app.gateway.automations_store import RulesEditError, put_rule
        from app.gateway.routers.automations import edit_rules, rule_versions

        self._automations_allowed()
        rule = draft["snapshot"]
        try:
            edit_rules(self._config(), lambda doc: put_rule(doc, name, rule), None, who=who, source="chat", via="chat", base_versions={name: version})
            return rule_versions(self._config(), name)[0]
        except RulesEditError as exc:
            raise BuilderRefused("the rules file refused the change (it may have changed since: draft it again)." if exc.status == 409 else "the rules file refused the change.") from exc

    # -- grants ------------------------------------------------------------------

    def _grant_plan(self, context: dict, arguments: dict) -> tuple[str, dict]:
        """The card's text and what a grant writes. It can add tool groups,
        give integrations and tools (turning an agent that uses tool groups,
        or has no access yet, into a per-tool list that keeps every tool it
        has now), set its skills list or model, and add standing grants. An
        integration named without tools gives its tools that read freely
        (Tier 1); others must be named. Every tool it gains is listed; nothing
        is ticked for the owner, and only the button confirms it."""
        from app.policy.grants import ACTION_CLASSES, grantable
        from app.policy.registration import shared_loader
        from omniharness.config.agents_config import INTEGRATION_PREFIXES
        from omniharness.tools.agent_access import CORE_TOOLS, integration_of

        user_id, _ = self._guard(context)
        agent = self._norm(context, "agent", str(arguments.get("agent") or ""))
        self._check_target(context, "agent", agent)
        if agent == LEAD_AGENT:
            raise BuilderRefused("the assistant's own access is changed in Agent Studio.")
        live, version = self._live(user_id, "agent", agent)
        if live is None:
            raise BuilderRefused(f"there is no agent called {agent!r}.")
        cfg = self._config()
        config = dict(live.get("config") or {})
        new = json.loads(json.dumps(config))
        integrations = [i for i in dict.fromkeys(arguments.get("integrations") or []) if isinstance(i, str)]
        tools = [t for t in dict.fromkeys(arguments.get("tools") or []) if isinstance(t, str)]
        groups = [g for g in dict.fromkeys(arguments.get("tool_groups") or []) if isinstance(g, str)]
        skills = arguments.get("skills")
        model = arguments.get("model")
        autonomy = [c for c in dict.fromkeys(arguments.get("autonomy") or []) if isinstance(c, str)]
        bad = [i for i in integrations if not i.startswith(INTEGRATION_PREFIXES)]
        if bad:
            raise BuilderRefused(f"not an integration id: {', '.join(bad)} (they start with local:, connector: or builtin:).")
        known_groups = {g.name for g in cfg.tool_groups}
        unknown = [g for g in groups if g not in known_groups]
        if unknown:
            raise BuilderRefused(f"no such tool group: {', '.join(unknown)}.")
        lines = [f"**Give the agent `{agent}` more** (based on version {version}). Nothing here is ticked for you; only the button confirms it:"]
        current_access = config.get(config_versions.TOOLS_KEY)
        if integrations or tools or current_access is not None and groups:
            # A per-tool list. One the agent does not have yet starts from
            # every tool it has now, so nothing it has is taken away.
            if current_access is None:
                group_of = {c.name: c.group for c in cfg.tools if getattr(c, "group", None)}
                have_i: list[str] = []
                have_t: list[str] = []
                for tool in self._assembled_tools(user_id, config):
                    if tool.name in CORE_TOOLS:
                        continue
                    try:
                        source = integration_of(tool, config_groups=group_of)
                    except LookupError:
                        continue
                    if source:
                        have_i.append(source)
                        have_t.append(tool.name)
                access = {"integrations": list(dict.fromkeys(have_i)), "tools": list(dict.fromkeys(have_t))}
                lines.append("- its tools become a per-tool list: what its tool groups and built-ins give it now, plus what is listed here (apps a chat selects no longer add to it, and the web researcher is not offered on a per-tool list)")
            else:
                access = {"integrations": list(current_access.get("integrations") or []), "tools": list(current_access.get("tools") or [])}
            for group in groups:
                integrations.append(f"builtin:{group}")
            for integration in dict.fromkeys(integrations):
                listed = self._integration_tools(user_id, integration)
                if not listed and integration.startswith("builtin:"):
                    continue  # a tool group this install offers no tools from
                if not listed:
                    raise BuilderRefused(f"{integration} has no tools for this account now (an app must be connected on the Connections page first; nothing is connected from here).")
                named = [t for t in tools if t in {n for n, _ in listed}]
                picked = named or [n for n, tier in listed if tier == 1]
                if integration not in access["integrations"]:
                    access["integrations"].append(integration)
                access["tools"] += [t for t in picked if t not in access["tools"]]
            access["tools"] += [t for t in tools if t not in access["tools"]]
            new[config_versions.TOOLS_KEY] = access
            added_i = [i for i in access["integrations"] if i not in ((current_access or {}).get("integrations") or [])]
            if current_access is not None and added_i:
                lines.append(f"- may use these integrations: {', '.join(added_i)}")
            elif current_access is None and integrations:
                lines.append(f"- may use these integrations: {', '.join(dict.fromkeys(integrations))}")
        elif groups:
            have = config.get("tool_groups")
            if have is not None:
                added = [g for g in groups if g not in have]
                if added:
                    lines.append(f"- tool groups added: {', '.join(added)}")
                new["tool_groups"] = [*have, *added]
        if isinstance(skills, list):
            known = {s.name for s in self._skills().load_skills(enabled_only=True)}
            wanted = [s for s in dict.fromkeys(skills) if isinstance(s, str) and s in known]
            if wanted != config.get("skills"):
                lines.append(f"- skills set to: {', '.join(wanted) or '(none)'}")
                new["skills"] = wanted
        if model:
            if cfg.get_model_config(str(model)) is None:
                raise BuilderRefused(f"no such model: {model!r}.")
            if str(model) != config.get("model"):
                lines.append(f"- model set to: {model}")
                new["model"] = str(model)
        adds = sorted(self._effective_tools(user_id, new) - self._effective_tools(user_id, config))
        if adds:
            lines.append(f"- so it may use: {', '.join(adds)}")
        if autonomy:
            ruleset = shared_loader(cfg.policy).load(notify=False)
            labels = {a.id: a for a in ACTION_CLASSES}
            refused = [why for c in autonomy for ok, why in [grantable(c, ruleset)] if not ok]
            if refused:
                raise BuilderRefused("not grantable: " + "; ".join(refused))
            have = set(config.get(config_versions.AUTONOMY_KEY) or [])
            autonomy = [c for c in autonomy if c not in have]
            for c in autonomy:
                lines.append(f"- may, on its own in a scheduled run: {labels[c].label} ({labels[c].allows})")
            if autonomy:
                new[config_versions.AUTONOMY_KEY] = sorted({*have, *autonomy})
        if new == config:
            raise BuilderRefused(f"{agent!r} already has all of that.")
        lines.append("")
        lines.append("A new app connection is never started from here: connect it on the Connections page first.")
        return "\n".join(lines), {"agent": agent, "version": version, "live": live, "config": new, "autonomy": bool(autonomy)}

    def grant(self, context: dict, *, agent: str, integrations: list[str], tools: list[str], autonomy: list[str], tool_groups: list[str] | None = None, skills: list[str] | None = None, model: str | None = None) -> str:
        arguments = {"agent": agent, "integrations": integrations, "tools": tools, "autonomy": autonomy, "tool_groups": tool_groups or [], "skills": skills, "model": model}
        try:
            confirmed = False
            action = self._confirmed("builder_grant", {"agent": agent}, button=True)
            confirmed = True
            user_id, thread_id = self._who(context)
            _, plan = self._grant_plan(context, arguments)
            snapshot = {**json.loads(json.dumps(plan["live"])), "config": plan["config"]}
            made = config_versions.write_agent(
                user_id, plan["agent"], snapshot, who=f"user:{user_id}", source="chat", base_version=plan["version"], sets_autonomy=plan["autonomy"], extra={"via": "chat", "thread_id": thread_id, "card_id": action.id}
            )
            return f"Gave `{plan['agent']}` what the card listed, as version {made.version} (source: chat)."
        except (config_versions.StaleWriteError, BuilderRefused) as exc:
            return _not_done("Nothing was changed", exc, confirmed)

    def _propose_access(self, context: dict, saved_by, agent: str, request: dict) -> str | None:
        """Right after a save that left access out: ONE permission card for the
        access the draft asked for (a builder_grant pending action, button
        only, its items listed). Returns its id, or None when there is
        nothing to ask for."""
        from datetime import UTC, datetime

        from app.policy.middleware import PolicyMiddleware
        from app.policy.models import PendingAction, Tier, default_expiry
        from app.policy.pending import PendingStore
        from app.policy.registration import shared_loader
        from app.policy.targets import resolve_targets

        groups = request.get("tool_groups")
        if "tool_groups" in request and groups is None:
            groups = [g.name for g in self._config().tool_groups]
        arguments = {"agent": agent, "integrations": list(request.get("integrations") or []), "tools": list(request.get("tools") or []), "autonomy": [], "tool_groups": list(groups or [])}
        if isinstance(request.get("skills"), list):
            arguments["skills"] = list(request["skills"])
        if request.get("model"):
            arguments["model"] = request["model"]
        try:
            note, _ = self._grant_plan(context, arguments)
        except BuilderRefused as exc:
            logger.info("builder: no permission card after saving %s: %s", agent, exc)
            return None
        policy = self._config().policy
        ruleset = shared_loader(policy).load(notify=False)
        targets = resolve_targets("builder_grant", arguments)
        card = PendingAction(
            plan_text="",
            tool_name="builder_grant",
            arguments=arguments,
            targets=targets,
            tier_at_statement=Tier.TIER_3,
            expires_at=default_expiry(datetime.now(UTC), ruleset.expires_after_seconds),
            thread_id=saved_by.thread_id,
            requester=saved_by.requester,
            origin=saved_by.origin,
            origin_source=saved_by.origin_source,
            owner_id=saved_by.owner_id,
            surface=dict(saved_by.surface or {}),
            private_read=saved_by.private_read,
        )
        card.plan_text = f"{PolicyMiddleware._plan_text('builder_grant', targets, card.requester, (), card.id, arguments, origin_note=card.origin_note())}\n\n{note}"
        PendingStore(directory=Path(policy.state_dir) / "pending").save(card)
        return card.id

    # -- undo -----------------------------------------------------------------------

    def _undo_plan(self, context: dict, arguments: dict) -> dict:
        """What an undo restores, as the card says it. An undo never changes
        what an agent may use or do: its tool list, tool groups, skills list
        and standing grants stay as they are now; where the older version had
        different ones, the card says so and points to builder_grant."""
        user_id, _ = self._guard(context)
        kind = str(arguments.get("kind") or "")
        if kind not in KINDS:
            raise BuilderRefused(f"cannot undo a {kind!r}.")
        name = self._norm(context, kind, str(arguments.get("name") or ""))
        self._check_target(context, kind, name)
        version = int(arguments.get("version") or 0)
        live, current = self._live(user_id, kind, name)
        if version != current:
            raise BuilderRefused(f"the {kind} {name!r} is at version {current}, not {version}; read it again before undoing.")
        history = self._history(user_id, kind, name)
        earlier = [v for v in history if v.version < version]
        if not earlier:
            raise BuilderRefused(f"version {version} of {name!r} has nothing before it to go back to.")
        target = earlier[-1]
        if target.snapshot is None and live is None:
            raise BuilderRefused(f"{name!r} is already removed.")
        restored = target.snapshot
        lines: list[str] = []
        button_only = ""
        if kind == "agent" and restored is not None:
            live_config = (live or {}).get("config") or {}
            config = dict(restored.get("config") or {})
            differs = [k for k in ACCESS_KEYS if config.get(k) != live_config.get(k)]
            for key in ACCESS_KEYS:
                if key in live_config:
                    config[key] = live_config[key]
                else:
                    config.pop(key, None)
            restored = {**restored, "config": config}
            if differs:
                lines.append(f"Version {target.version} had different {', '.join(differs)}; they stay as they are now. To change what it may use, propose builder_grant (button only).")
            else:
                lines.append("What it may use and do on its own stays as it is now.")
        elif kind == "skill" and restored is not None and live is not None:
            old_meta, _ = self._skill_meta(((restored.get("files") or {}).get(SKILL_MD)) or "")
            new_meta, _ = self._skill_meta(((live.get("files") or {}).get(SKILL_MD)) or "")
            if old_meta.get("allowed-tools") != new_meta.get("allowed-tools"):
                raise BuilderRefused(f"version {target.version} of the skill allows different tools; restoring it would change what agents using it may use, so do it in Skill Studio.")
        elif kind == "skill" and restored is None and live is not None and self._skill_meta(((live.get("files") or {}).get(SKILL_MD)) or "")[0].get("allowed-tools") is not None:
            raise BuilderRefused("removing this skill would lift the tool limits it sets for agents that use it, so do it in Skill Studio.")
        elif kind == "automation" and restored is not None:
            line, button_only = self._automation_card(user_id, restored)
            lines.append(line)
        what = f"remove the {kind} {name!r} (undo its creation)" if target.snapshot is None else f"restore version {target.version} of the {kind} {name!r}"
        text = f"**Undo**: {what}, as a new version after {version}." + ("\n\n" + "\n".join(lines) if lines else "")
        return {"kind": kind, "name": name, "version": version, "to": target.version, "restored": restored, "text": text, "button_only": button_only}

    def _history(self, user_id: str, kind: str, name: str) -> list:
        if kind == "agent":
            history = config_versions.agent_history(user_id, name)
        elif kind == "skill":
            history = config_versions.skill_history(name, self._skills())
        else:
            from app.gateway.routers.automations import rule_versions

            history = rule_versions(self._config(), name)[1]
        if history and history[0].source != "existing":
            # The first version created it: version 0 is "before it", and
            # undoing the create writes a deleted version (FR-020).
            return [config_versions.Version(version=0, at="", who="", source="", changed=[], snapshot=None), *history]
        return history

    def undo(self, context: dict, *, kind: str, name: str, version: int) -> str:
        try:
            confirmed = False
            self._confirmed("builder_undo", {"kind": kind, "name": name, "version": version})
            confirmed = True
            user_id, _ = self._who(context)
            plan = self._undo_plan(context, {"kind": kind, "name": name, "version": version})
            who = f"user:{user_id}"
            if plan["kind"] == "automation":
                from app.gateway.automations_store import RulesEditError
                from app.gateway.routers.automations import rule_versions, undo_rule

                try:
                    undo_rule(self._config(), plan["name"], plan["to"], base_version=version, who=who, via="chat")
                except RulesEditError as exc:
                    raise BuilderRefused("the rules file refused the undo (it may have changed since: read it again)." if exc.status == 409 else "the rules file refused the undo.") from exc
                new_version = rule_versions(self._config(), plan["name"])[0]
            else:
                # As config_versions.undo does, with version 0 (before a create)
                # allowed: the restored state is written as a NEW version, with
                # the agent's access as it is now (_undo_plan).
                restored = plan["restored"]
                if plan["kind"] == "agent":
                    made = config_versions.write_agent(user_id, plan["name"], restored, who=who, source="undo", base_version=version)
                else:
                    files = (restored or {}).get("files") if restored is not None else None
                    made = config_versions.write_skill(plan["name"], files, who=who, source="undo", base_version=version, replace_all=True, storage=self._skills())
                new_version = made.version
            return f"Undone: the {plan['kind']} `{plan['name']}` is now version {new_version} (source: undo)."
        except (config_versions.StaleWriteError, BuilderRefused) as exc:
            return _not_done("Nothing was undone", exc, confirmed)
