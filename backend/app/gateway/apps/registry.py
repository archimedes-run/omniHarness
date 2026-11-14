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
from app.gateway.apps.service import load_app, raise_card_if_needed
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
) -> RegistrationResult:
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
        html, script_hashes = bundle_mod.inline(files, prelude=bundle_mod.platform_shim())
    except bundle_mod.BundleError as exc:
        raise AppRegistrationError(exc.code, str(exc)) from exc
    if app_id is not None:
        try:
            cv.validate_app_id(app_id)
        except ValueError as exc:
            raise AppRegistrationError("invalid_request", str(exc)) from exc
    else:
        app_id = _new_app_id(normalised["name"], owner_id)
    digest = cv.write_app_bundle(owner_id, html)
    snapshot = {"manifest": normalised, "manifest_hash": manifest_hash(normalised), "bundle_hash": digest, "script_hashes": script_hashes}
    version = cv.write_app(owner_id, app_id, snapshot, who=REGISTRAR, source="code_job")
    app = load_app(owner_id, app_id, version.version)
    kind, source_label = origin
    card = await raise_card_if_needed(repo, app, thread_id=thread_id, suggestion=kind != "user", suggestion_source=(source_label or "content read earlier")[:200] if kind != "user" else None)
    await repo.audit(owner_id=owner_id, app_id=app_id, event="app_registered", detail={"version": app.version, "manifest_hash": app.manifest_hash, "bundle_hash": digest, "card": card["id"] if card else None})
    return RegistrationResult(app_id=app_id, version=app.version, manifest_hash=app.manifest_hash, needs_approval=card is not None, card_id=card["id"] if card else None)
