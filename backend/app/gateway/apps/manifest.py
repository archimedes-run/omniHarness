"""`omni-app.json`: validation and the manifest hash (Spec 011 FR-001, FR-002, FR-004).

A manifest names catalog entries, a subset of each entry's allowed fields,
params satisfying the entry's typed, bounded schema, and a refresh interval.
Unknown keys anywhere are refused; there are no free-form params.

The manifest hash is SHA-256 of the canonical JSON of `sources` only (sorted
keys, no whitespace, defaults filled in, fields in catalog order), so a code-
only change keeps its approval and any change to `sources` needs a new one.
`name` and `description` are not in the hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.gateway.apps.catalog import REFRESH_MAX_S, REFRESH_MIN_S, get_entry, valid_timezone

SOURCE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
NAME_MAX = 60
DESCRIPTION_MAX = 300
SOURCES_MAX = 12


class ManifestError(ValueError):
    pass


def _check_keys(obj: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise ManifestError(f"{where}: unknown key(s) {', '.join(unknown)}")


def _param(entry_id: str, name: str, spec, value: Any) -> Any:
    where = f"{entry_id} param {name}"
    if spec.type == "integer":
        if not isinstance(value, int) or isinstance(value, bool) or not (spec.minimum <= value <= spec.maximum):
            raise ManifestError(f"{where} must be an integer from {spec.minimum} to {spec.maximum}")
        return value
    if spec.type == "enum":
        if value not in spec.values:
            raise ManifestError(f"{where} must be one of {', '.join(spec.values)}")
        return value
    if spec.type == "timezone":
        if not valid_timezone(value):
            raise ManifestError(f"{where} must be an IANA time zone")
        return value
    raise ManifestError(f"{where} has an unknown type")


def validate_manifest(raw: Any) -> dict:
    """The normalised manifest, or ManifestError naming the first problem."""
    if not isinstance(raw, dict):
        raise ManifestError("the manifest must be a JSON object")
    _check_keys(raw, {"schema", "name", "description", "sources"}, "manifest")
    if raw.get("schema") != 1 or isinstance(raw.get("schema"), bool):
        raise ManifestError("manifest: schema must be 1")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > NAME_MAX:
        raise ManifestError(f"manifest: name must be 1 to {NAME_MAX} characters")
    description = raw.get("description", "")
    if not isinstance(description, str) or len(description) > DESCRIPTION_MAX:
        raise ManifestError(f"manifest: description must be at most {DESCRIPTION_MAX} characters")
    sources = raw.get("sources")
    if not isinstance(sources, dict) or not (1 <= len(sources) <= SOURCES_MAX):
        raise ManifestError(f"manifest: sources must name 1 to {SOURCES_MAX} sources")
    out: dict[str, dict] = {}
    for source_name, spec in sources.items():
        if not isinstance(source_name, str) or not SOURCE_NAME.match(source_name):
            raise ManifestError(f"source name {source_name!r} must match [a-z][a-z0-9_]{{0,31}}")
        where = f"source {source_name}"
        if not isinstance(spec, dict):
            raise ManifestError(f"{where} must be an object")
        _check_keys(spec, {"use", "params", "fields", "refresh_s"}, where)
        entry = get_entry(spec.get("use")) if isinstance(spec.get("use"), str) else None
        if entry is None:
            raise ManifestError(f"{where}: use must name a catalog entry")
        params = spec.get("params", {})
        if not isinstance(params, dict):
            raise ManifestError(f"{where}: params must be an object")
        _check_keys(params, set(entry.params), f"{where} params")
        normalised: dict[str, Any] = {}
        for pname, pspec in entry.params.items():
            if pname in params:
                normalised[pname] = _param(entry.id, pname, pspec, params[pname])
            elif pspec.required:
                raise ManifestError(f"{where}: param {pname} is required")
            elif pspec.default is not None:
                # An optional param with no default (added later, e.g. the
                # GitHub source's tz) is left out, so manifests approved
                # before it existed keep their hash.
                normalised[pname] = pspec.default
        fields = spec.get("fields")
        if not isinstance(fields, list) or not fields or not all(isinstance(f, str) for f in fields):
            raise ManifestError(f"{where}: fields must be a non-empty list of field names")
        extra = sorted(set(fields) - set(entry.fields))
        if extra:
            raise ManifestError(f"{where}: field(s) {', '.join(extra)} are not allowed for {entry.id}")
        refresh = spec.get("refresh_s", entry.default_refresh_s)
        if not isinstance(refresh, int) or isinstance(refresh, bool) or not (REFRESH_MIN_S <= refresh <= REFRESH_MAX_S):
            raise ManifestError(f"{where}: refresh_s must be an integer from {REFRESH_MIN_S} to {REFRESH_MAX_S}")
        out[source_name] = {"use": entry.id, "params": normalised, "fields": [f for f in entry.fields if f in fields], "refresh_s": refresh}
    return {"schema": 1, "name": name.strip(), "description": description, "sources": out}


def manifest_hash(manifest: dict) -> str:
    """SHA-256 of the canonical JSON of the (normalised) manifest's sources."""
    canonical = json.dumps(manifest["sources"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
