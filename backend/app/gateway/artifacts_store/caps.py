"""Artifact store caps (Spec 012 FR-004, plan Q3): tracked defaults, in code.

A write over any cap is refused before anything is stored.
"""

from __future__ import annotations

MB = 1024 * 1024

#: Canonical content of a text kind (markdown, code, svg, mermaid, chart).
TEXT_VERSION_BYTES = 2 * MB
#: An image or file version.
BINARY_VERSION_BYTES = 10 * MB
#: Versions kept per artifact; beyond it the oldest that is neither v1 nor the
#: latest is pruned (nothing in S1 references an older version: no exports,
#: shares or apps yet).
VERSIONS_PER_ARTIFACT = 200
#: Distinct blobs per owner.
OWNER_BYTES = 1024 * MB
#: Display-sanitised title and note lengths.
TITLE_CHARS = 120
NOTE_CHARS = 300
#: Latest text kept for search.
SEARCH_TEXT_CHARS = 200_000
#: React sources of one version (canonical JSON of {entry, files}) and the
#: built, inlined bundle (FR-004).
REACT_SOURCE_BYTES = 2 * MB
REACT_BUNDLE_BYTES = 2 * MB
#: The react build's wall time in the sandbox (FR-017).
REACT_BUILD_SECONDS = 120
#: Build log tail kept with a failed build.
BUILD_LOG_CHARS = 4000
#: A webapp's stored file set, decoded (FR-029: the html file sets).
WEBAPP_FILES_BYTES = 2 * MB
