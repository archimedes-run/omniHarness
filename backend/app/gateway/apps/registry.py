"""Registering an app (Spec 011 FR-007, FR-028).

Called by the GATEWAY after a verified app-mode coding job, never by the worker,
an agent, a script, a scheduled run or the frame: there is no HTTP route for it.
It validates the manifest against the catalog (and every connector source
against the three read-only checks), inlines the bundle, computes the script
hashes, scans it, stores a new version, and raises an App access card when the
version's manifest hash has no active grant.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.gateway.apps import bundle as bundle_mod
from app.gateway.apps.catalog import get_entry
from app.gateway.apps.checks import read_only_refusal, rules_in_force
from app.gateway.apps.manifest import ManifestError, manifest_hash, validate_manifest
from app.gateway.apps.service import clean_source, load_app, raise_card_if_needed, served
from omniharness.config import config_versions as cv

#: Who a registered version is recorded as.
REGISTRAR = "code_job"


class AppRegistrationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RegistrationResult:
    app_id: str
    version: int
    manifest_hash: str
    needs_approval: bool
    card_id: str | None


NOTE_TEXT_MAX = 300
#: The person's own request shown on the card ("You asked:").
NOTE_REQUEST_MAX = 2000


def clean_note(note: dict, *, user_led: bool = False) -> dict:
    """The version card's note: fixed keys, plain short text only. The
    person's request is kept only for a version their own message led to."""
    out: dict = {}
    request = note.get("request")
    if user_led and isinstance(request, str):
        words = " ".join("".join(c if c.isprintable() else " " for c in request).split())[:NOTE_REQUEST_MAX]
        if words:
            out["request"] = words
    text = note.get("description")
    if isinstance(text, str):
        flat = " ".join("".join(c if c.isprintable() else " " for c in text).split())
        if len(flat) > NOTE_TEXT_MAX:
            # At a word boundary, with an ellipsis: never "...; enforc".
            head = flat[:NOTE_TEXT_MAX].rsplit(" ", 1)[0].rstrip(" ,;:.-")
            flat = head + "…"
        out["description"] = flat
    if note.get("checks") == "passed":
        out["checks"] = "passed"
    if isinstance(note.get("keeps"), int):
        out["keeps"] = note["keeps"]
    if note.get("kind") == "version":
        out["kind"] = "version"
    return out


def _new_app_id(name: str, owner_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "app"
    existing = set(cv.app_ids(owner_id))
    if slug not in existing and re.match(r"^[a-z0-9]", slug):
        return slug
    while True:
        candidate = f"{slug}-{secrets.token_hex(3)}"
        if candidate not in existing:
            return candidate


async def register_app(
    app_state,
    *,
    owner_id: str,
    manifest: dict,
    files: dict[str, bytes],
    app_id: str | None = None,
    thread_id: str | None = None,
    origin: tuple[Literal["user", "content"], str | None] = ("user", None),
    hold: bool = False,
    note: dict | None = None,
    shots: dict[str, bytes] | None = None,
) -> RegistrationResult:
    """`hold`: a new version of an existing app waits on the owner's button
    whatever led to it (an update, or a design pass on a registered app);
    `note`: what the version card shows (the system's check result, the
    assistant's description, labelled as such), stored with the version."""
    repo = getattr(app_state, "app_repo", None)
    if repo is None:
        raise AppRegistrationError("apps_unavailable", "apps need the gateway's SQL store")
    try:
        normalised = validate_manifest(manifest)
    except ManifestError as exc:
        raise AppRegistrationError("invalid_manifest", str(exc)) from exc
    rules = rules_in_force(app_state)
    now = datetime.now(UTC)
    for name, spec in normalised["sources"].items():
        entry = get_entry(spec["use"])
        reason = read_only_refusal(entry, entry.arguments(spec["params"], now) if entry.arguments else {}, rules)
        if reason is not None:
            raise AppRegistrationError("source_refused", f"source {name}: {reason}")
    try:
        html, script_hashes = bundle_mod.inline(files)
    except bundle_mod.BundleError as exc:
        raise AppRegistrationError(exc.code, str(exc)) from exc
    if app_id is not None:
        try:
            cv.validate_app_id(app_id)
        except ValueError as exc:
            raise AppRegistrationError("invalid_request", str(exc)) from exc
    else:
        app_id = _new_app_id(normalised["name"], owner_id)
    kind, source_label = origin
    from_content = kind != "user"
    # Led by content, a new version of an existing app (even a code-only one)
    # waits on the owner's button; the last served version keeps serving.
    existing = bool(cv.app_history(owner_id, app_id))
    held = (from_content or hold) and existing
    digest = cv.write_app_bundle(owner_id, html)
    snapshot = {"manifest": normalised, "manifest_hash": manifest_hash(normalised), "bundle_hash": digest, "script_hashes": script_hashes}
    if held and await repo.active_grant(owner_id=owner_id, app_id=app_id, manifest_hash=snapshot["manifest_hash"]):
        # Same sources, already granted: the card offers the version itself.
        note = {**(note or {}), "kind": "version", "keeps": (await served(repo, owner_id, app_id)).version}
    if note:
        snapshot["note"] = clean_note(note, user_led=kind == "user")
    stored_shots = {}
    for theme, png in (shots or {}).items():
        if theme in ("light", "dark") and isinstance(png, bytes):
            try:
                stored_shots[theme] = cv.write_app_shot(owner_id, png)
            except ValueError:
                continue  # not a PNG of the allowed size: left out
    if stored_shots:
        snapshot["shots"] = stored_shots
    if thread_id and not existing:
        snapshot["thread_id"] = thread_id  # the chat that built the app (updates must come from it)
    elif thread_id and existing:
        first = cv.app_history(owner_id, app_id)[0].snapshot or {}
        if first.get("thread_id"):
            snapshot["thread_id"] = first["thread_id"]
    version = cv.write_app(owner_id, app_id, snapshot, who=REGISTRAR, source="code_job", held=held)
    app = load_app(owner_id, app_id, version.version)
    label = clean_source(source_label) or "content read earlier"
    card = await raise_card_if_needed(repo, app, thread_id=thread_id, suggestion=from_content, suggestion_source=label if from_content else None, held=held)
    await repo.audit(owner_id=owner_id, app_id=app_id, event="app_registered", detail={"version": app.version, "manifest_hash": app.manifest_hash, "bundle_hash": digest, "card": card["id"] if card else None, "held": held})
    return RegistrationResult(app_id=app_id, version=app.version, manifest_hash=app.manifest_hash, needs_approval=card is not None, card_id=card["id"] if card else None)
