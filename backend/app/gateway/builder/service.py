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
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
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
            owner = config_versions.skill_owner(name, storage)
            if owner is not None and owner != user_id:
                raise BuilderRefused(f"the skill {name!r} belongs to another account.")
            if not storage.custom_skill_exists(name):
                if storage.public_skill_exists(name):
                    raise BuilderRefused(f"{name!r} is an installed skill, which is not edited from chat. Offer to make a custom copy under a new name.")
                return None, config_versions.skill_version(name, storage)
            history = config_versions.skill_history(name, storage)
            files = history[-1].snapshot if history and history[-1].snapshot is not None else {"files": {SKILL_MD: storage.read_custom_skill(name)}}
            return files, config_versions.skill_version(name, storage)
        self._automations_allowed()
        from app.gateway.automations_store import RulesEditError
        from app.gateway.routers.automations import rule_versions

        try:
            version, _, on_file = rule_versions(self._config(), name)
        except RulesEditError as exc:
            raise BuilderRefused(str(exc)) from exc
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
        access = {key: [v for v in fields.get(key) or [] if isinstance(v, str)] for key in ACCESS_FIELDS if fields.get(key)}
        if access:
            notes.append("Tool access is not saved with this draft: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in access.items()) + ". It needs builder_grant, which only the card's button confirms.")
        return {"config": config, "soul": soul}, dropped, notes

    def _compose_skill(self, name: str, fields: dict, live: dict | None) -> tuple[dict, list[str], list[str]]:
        files = dict((live or {}).get("files") or {})
        description, body = "", ""
        match = _FRONTMATTER.match(files.get(SKILL_MD, ""))
        if match:
            import yaml

            try:
                meta = yaml.safe_load(match.group(1)) or {}
            except yaml.YAMLError:
                meta = {}
            description = str(meta.get("description") or "") if isinstance(meta, dict) else ""
            body = match.group(2).strip()
        if isinstance(fields.get("description"), str):
            description = fields["description"].strip()
        if isinstance(fields.get("body"), str):
            body = fields["body"].strip()
        notes = []
        unknown = [key for key in fields if key not in ("description", "body")]
        if unknown:
            notes.append(f"Not part of a skill here, left out: {', '.join(sorted(unknown))}.")
        meta_text = json.dumps(description, ensure_ascii=False)
        files[SKILL_MD] = f"---\nname: {name}\ndescription: {meta_text}\n---\n\n{body}\n"
        return {"files": files}, [], notes

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

    # -- validation, shared by the card and the save --------------------------

    def _validate(self, user_id: str, draft: dict) -> None:
        kind, name, snapshot = draft["kind"], draft["name"], draft["snapshot"]
        if kind == "agent":
            if not (snapshot.get("soul") or "").strip():
                raise BuilderRefused("the agent has no instructions yet.")
            return
        if kind == "skill":
            storage = self._skills()
            try:
                storage.validate_skill_markdown_content(name, snapshot["files"][SKILL_MD])
            except ValueError as exc:
                raise BuilderRefused(f"the skill is not valid yet: {exc}") from exc
            return
        self._validate_rule(user_id, snapshot)

    def _validate_rule(self, user_id: str, rule: dict) -> None:
        from app.gateway.automations_store import RulesEditError, put_rule, read_rules, validate
        from app.gateway.trigger_engine_wiring import SUPPORTED_SOURCE_TYPES, _resolve_rules_path
        from app.trigger_engine.config import standard_cron_problem

        cfg = self._config().trigger_engine
        if not getattr(cfg, "rules_path", ""):
            raise BuilderRefused("no rules file is configured (trigger_engine.rules_path), so automations cannot be saved; set one in config.yaml first.")
        match = rule.get("match")
        schedule = match.get("schedule") if isinstance(match, dict) else None
        if rule.get("type") == "cron" and schedule and len(str(schedule).split()) != 5:
            raise BuilderRefused(f"the schedule {schedule!r} {standard_cron_problem(schedule) or 'is not a five-field cron expression'}.")
        agent = rule.get("agent")
        if isinstance(agent, str) and agent.strip().lower() not in ("", LEAD_AGENT):
            from omniharness.config.agents_config import load_agent_config

            try:
                load_agent_config(agent.strip().lower(), user_id=user_id)
            except (FileNotFoundError, ValueError) as exc:
                raise BuilderRefused(f"there is no agent called {agent.strip().lower()!r}; a rule runs only as an agent that exists.") from exc
        try:
            current = read_rules(_resolve_rules_path(cfg)).doc
            validate(put_rule(current, rule["id"], rule), SUPPORTED_SOURCE_TYPES, current)
        except RulesEditError as exc:
            raise BuilderRefused(f"the automation engine would refuse it: {exc}") from exc
        except (OSError, ValueError) as exc:
            raise BuilderRefused(f"could not read the rules file: {exc}") from exc

    # -- the tools ---------------------------------------------------------------

    def draft(self, context: dict, *, kind: str, name: str, fields: dict[str, Any], guessed: list[str], replace_current: bool) -> str:
        try:
            user_id, thread_id = self._guard(context)
            if kind == "mcp_server":
                return MCP_HANDOFF.format(request=str((fields or {}).get("request") or name or "(what they described)")[:500])
            if kind not in KINDS:
                raise BuilderRefused(f"the builder makes agents, skills and automations, not {kind!r}.")
            name = self._norm(context, kind, name)
            self._check_target(context, kind, name)
            current = drafts.active(user_id, thread_id)
            if current and (current.get("kind"), current.get("name")) != (kind, name) and not replace_current:
                return (
                    f"Nothing was drafted: this chat is already building the {current.get('kind')} {current.get('title') or current.get('name')!r}. "
                    "Ask the user whether to drop that draft and start this one; if they agree, call builder_draft again with replace_current=true."
                )
            live, version = self._live(user_id, kind, name)
            snapshot, dropped, notes = self._compose(user_id, kind, name, dict(fields or {}), live)
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
                "created_at": drafts.now(),
            }
            problem = None
            try:
                self._validate(user_id, draft)
            except BuilderRefused as exc:
                problem = str(exc)
            drafts.put_draft(user_id, thread_id, draft)
            text = render_draft(draft, live=live, live_version=version)
            nxt = f"Not ready to save: {problem} Revise it with builder_draft." if problem else f"To propose saving it, call builder_save with draft_id {draft['id']!r}."
            return f"Draft `{draft['id']}` recorded in this chat (nothing saved).\n\n{text}\n\n{nxt}"
        except BuilderRefused as exc:
            return f"Nothing was drafted: {exc}"

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

    def precheck(self, tool_name: str, arguments: dict, context: dict) -> tuple[str | None, str, bool, dict]:
        try:
            if tool_name == "builder_save":
                draft_id = str(arguments.get("draft_id") or "")
                if not draft_id:
                    # The chat's current draft, pinned on the card: the card
                    # saves exactly the draft it shows.
                    user_id, thread_id = self._guard(context)
                    draft_id = str((drafts.active(user_id, thread_id) or {}).get("draft_id") or "")
                draft, live, version = self._ready_draft(context, draft_id)
                return None, render_draft(draft, live=live, live_version=version), True, {**arguments, "draft_id": draft_id}
            if tool_name == "builder_grant":
                return None, self._grant_plan(context, arguments)[0], False, arguments
            if tool_name == "builder_undo":
                return None, self._undo_plan(context, arguments)["text"], False, arguments
            return f"{tool_name} is not a builder proposal.", "", False, arguments
        except BuilderRefused as exc:
            return str(exc), "", False, arguments

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
        if button and (action.confirmation or {}).get("via") != "button":
            raise BuilderRefused("tool access and standing grants are confirmed only with the card's button; nothing was changed.")
        return action

    def save(self, context: dict, *, draft_id: str) -> str:
        try:
            action = self._confirmed("builder_save", {"draft_id": draft_id})
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
            logger.info("builder: saved %s %r as version %s (thread %s, card %s)", kind, name, new_version, thread_id, action.id)
            verb = "Created" if draft.get("mode") == "create" else "Saved"
            return f"{verb} the {kind} {draft.get('title') or name!r} as version {new_version} (source: chat). To undo it, propose builder_undo with version {new_version}."
        except config_versions.StaleWriteError as exc:
            return f"Nothing was saved: {exc}"
        except BuilderRefused as exc:
            return f"Nothing was saved: {exc}"

    def _save_skill(self, user_id: str, name: str, draft: dict, live: dict | None, version: int, who: str, extra: dict) -> int:
        from omniharness.skills.security_scanner import scan_skill_content

        storage = self._skills()
        content = draft["snapshot"]["files"][SKILL_MD]
        scan = _run_sync(scan_skill_content(content, executable=False, location=f"{name}/{SKILL_MD}", app_config=self._config()))
        if scan.decision == "block":
            raise BuilderRefused(f"the security scan blocked the skill: {scan.reason}")
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
            raise BuilderRefused(str(exc)) from exc

    # -- grants ------------------------------------------------------------------

    def _grant_plan(self, context: dict, arguments: dict) -> tuple[str, dict]:
        from app.policy.grants import ACTION_CLASSES, grantable
        from app.policy.registration import shared_loader

        user_id, _ = self._guard(context)
        agent = self._norm(context, "agent", str(arguments.get("agent") or ""))
        self._check_target(context, "agent", agent)
        if agent == LEAD_AGENT:
            raise BuilderRefused("the assistant's own access is changed in Agent Studio.")
        live, version = self._live(user_id, "agent", agent)
        if live is None:
            raise BuilderRefused(f"there is no agent called {agent!r}.")
        config = dict(live.get("config") or {})
        integrations = [i for i in arguments.get("integrations") or [] if isinstance(i, str)]
        tools = [t for t in arguments.get("tools") or [] if isinstance(t, str)]
        autonomy = [c for c in arguments.get("autonomy") or [] if isinstance(c, str)]
        lines = [f"**Give the agent `{agent}` more** (based on version {version}); nothing here is ticked for you:"]
        current_access = config.get(config_versions.TOOLS_KEY)
        if integrations or tools:
            from omniharness.config.agents_config import INTEGRATION_PREFIXES

            if current_access is None:
                raise BuilderRefused(f"{agent!r} uses tool groups, not a per-tool list; set its tool access in Agent Studio first.")
            bad = [i for i in integrations if not i.startswith(INTEGRATION_PREFIXES)]
            if bad:
                raise BuilderRefused(f"not an integration id: {', '.join(bad)} (they start with local:, connector: or builtin:).")
            new_i = [i for i in dict.fromkeys(integrations) if i not in (current_access.get("integrations") or [])]
            new_t = [t for t in dict.fromkeys(tools) if t not in (current_access.get("tools") or [])]
            if new_i:
                lines.append(f"- may use these integrations: {', '.join(new_i)}")
            if new_t:
                lines.append(f"- may use these tools (each keeps its own tier): {', '.join(new_t)}")
            integrations, tools = new_i, new_t
        if autonomy:
            ruleset = shared_loader(self._config().policy).load(notify=False)
            labels = {a.id: a for a in ACTION_CLASSES}
            refused = [why for c in autonomy for ok, why in [grantable(c, ruleset)] if not ok]
            if refused:
                raise BuilderRefused("not grantable: " + "; ".join(refused))
            have = set(config.get(config_versions.AUTONOMY_KEY) or [])
            autonomy = [c for c in dict.fromkeys(autonomy) if c not in have]
            for c in autonomy:
                lines.append(f"- may, on its own in a scheduled run: {labels[c].label} ({labels[c].allows})")
        if not (integrations or tools or autonomy):
            raise BuilderRefused(f"{agent!r} already has all of that.")
        lines.append("")
        lines.append("A new app connection is never started from here: connect it on the Connections page first.")
        return "\n".join(lines), {"agent": agent, "version": version, "live": live, "integrations": integrations, "tools": tools, "autonomy": autonomy}

    def grant(self, context: dict, *, agent: str, integrations: list[str], tools: list[str], autonomy: list[str]) -> str:
        arguments = {"agent": agent, "integrations": integrations, "tools": tools, "autonomy": autonomy}
        try:
            action = self._confirmed("builder_grant", {"agent": agent}, button=True)
            user_id, thread_id = self._who(context)
            _, plan = self._grant_plan(context, arguments)
            snapshot = json.loads(json.dumps(plan["live"]))
            config = snapshot.setdefault("config", {})
            if plan["integrations"] or plan["tools"]:
                access = dict(config.get(config_versions.TOOLS_KEY) or {})
                access["integrations"] = [*(access.get("integrations") or []), *plan["integrations"]]
                access["tools"] = [*(access.get("tools") or []), *plan["tools"]]
                config[config_versions.TOOLS_KEY] = access
            if plan["autonomy"]:
                config[config_versions.AUTONOMY_KEY] = sorted({*(config.get(config_versions.AUTONOMY_KEY) or []), *plan["autonomy"]})
            made = config_versions.write_agent(
                user_id, plan["agent"], snapshot, who=f"user:{user_id}", source="chat", base_version=plan["version"], sets_autonomy=bool(plan["autonomy"]), extra={"via": "chat", "thread_id": thread_id, "card_id": action.id}
            )
            return f"Gave {plan['agent']!r} what the card listed, as version {made.version} (source: chat)."
        except config_versions.StaleWriteError as exc:
            return f"Nothing was changed: {exc}"
        except BuilderRefused as exc:
            return f"Nothing was changed: {exc}"

    # -- undo -----------------------------------------------------------------------

    def _undo_plan(self, context: dict, arguments: dict) -> dict:
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
        what = f"remove the {kind} {name!r} (undo its creation)" if target.snapshot is None else f"restore version {target.version} of the {kind} {name!r}"
        return {"kind": kind, "name": name, "version": version, "to": target.version, "text": f"**Undo**: {what}, as a new version after {version}. Standing grants and tool access stay as they are."}

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
            self._confirmed("builder_undo", {"kind": kind, "name": name, "version": version})
            user_id, _ = self._who(context)
            plan = self._undo_plan(context, {"kind": kind, "name": name, "version": version})
            who = f"user:{user_id}"
            if plan["kind"] == "automation":
                from app.gateway.automations_store import RulesEditError
                from app.gateway.routers.automations import rule_versions, undo_rule

                try:
                    undo_rule(self._config(), plan["name"], plan["to"], base_version=version, who=who, via="chat")
                except RulesEditError as exc:
                    raise BuilderRefused(str(exc)) from exc
                new_version = rule_versions(self._config(), plan["name"])[0]
            else:
                # As config_versions.undo does, with version 0 (before a create)
                # allowed: the restored state is written as a NEW version.
                target = next(v for v in self._history(user_id, plan["kind"], plan["name"]) if v.version == plan["to"])
                if plan["kind"] == "agent":
                    made = config_versions.write_agent(user_id, plan["name"], target.snapshot, who=who, source="undo", base_version=version)
                else:
                    files = (target.snapshot or {}).get("files") if target.snapshot is not None else None
                    made = config_versions.write_skill(plan["name"], files, who=who, source="undo", base_version=version, replace_all=True, storage=self._skills())
                new_version = made.version
            return f"Undone: the {plan['kind']} {plan['name']!r} is now version {new_version} (source: undo)."
        except config_versions.StaleWriteError as exc:
            return f"Nothing was undone: {exc}"
        except BuilderRefused as exc:
            return f"Nothing was undone: {exc}"
