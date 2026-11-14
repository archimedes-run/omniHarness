"""ArtifactController port: how the artifact tools reach the Artifact store (Spec 012, Slice 1).

The store (app.gateway.artifacts_store) lives in the gateway, which the
harness must not import, so the gateway registers one implementation here at
startup, as it does for the ledger and the builder. The artifact tools are
offered only while one is registered.

Every method is SYNCHRONOUS (the store uses its own synchronous engine, like
the ledger). `context` is the run's runtime context, server-set (thread_id,
user_id, run_id, ...), plus the turn's messages the tool hands over for
lineage (MESSAGES_KEY); never anything the model chose. Each method returns
(text for the model, card binding or None).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

#: Where a tool hands the controller the turn's messages (lineage, FR-007).
MESSAGES_KEY = "_artifact_messages"
#: Where a tool hands the controller its own tool call id (card binding).
TOOL_CALL_KEY = "_artifact_tool_call_id"


@runtime_checkable
class ArtifactController(Protocol):
    def create(self, context: dict, *, kind: str, title: str, content: Any, language: str | None, source_path: str | None, note: str | None) -> tuple[str, dict | None]: ...

    def update(self, context: dict, *, artifact_id: str, base_version: int, content: Any, edits: list[dict] | None, language: str | None, note: str | None) -> tuple[str, dict | None]: ...

    def read(self, context: dict, *, artifact_id: str, version: int | None) -> str: ...

    def read_bound(self, context: dict, *, artifact_id: str, version: int | None) -> tuple[str, dict | None]: ...

    def list(self, context: dict, *, query: str | None, kind: str | None, limit: int | None) -> str: ...


_controller: ArtifactController | None = None


def get_artifact_controller() -> ArtifactController | None:
    return _controller


def set_artifact_controller(controller: ArtifactController | None) -> None:
    global _controller
    _controller = controller
