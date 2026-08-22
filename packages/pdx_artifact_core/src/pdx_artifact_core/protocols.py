"""Runtime protocols (ToolExecutor, Verifier, StorageAdapter)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolExecutor(Protocol):
    """Transport-agnostic tool execution (HTTP, MCP, callable, …)."""

    def execute(
        self,
        request: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Return a ToolResult-shaped mapping (see tool_result.v1.schema.json)."""
        ...


@runtime_checkable
class Verifier(Protocol):
    """Pluggable verification check."""

    @property
    def verifier_id(self) -> str: ...

    def verify(
        self,
        check: str,
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Return a verifier_result_v1-shaped mapping."""
        ...


@runtime_checkable
class StorageAdapter(Protocol):
    """Resolve opaque artifact URIs; never persist signed URLs or secrets."""

    def resolve(self, uri: str) -> Any: ...

    def exists(self, uri: str) -> bool: ...


@runtime_checkable
class EventSink(Protocol):
    """Receive bounded product-neutral run events."""

    def emit(self, event: Mapping[str, Any]) -> None: ...


@runtime_checkable
class CheckpointRepository(Protocol):
    """Persist immutable run snapshots without prescribing a database."""

    def put_if_absent(self, snapshot: Mapping[str, Any]) -> bool:
        """Store a new snapshot; return false when its identity already exists."""
        ...

    def get(self, snapshot_id: str) -> Mapping[str, Any] | None:
        """Return an isolated snapshot value, or none when it does not exist."""
        ...

    def compare_and_set(
        self,
        snapshot_id: str,
        expected_version: int,
        snapshot: Mapping[str, Any],
    ) -> bool:
        """Replace only the expected version; return false on conflict."""
        ...


@runtime_checkable
class DecisionRepository(Protocol):
    """Atomically record and retrieve product-neutral approval decisions."""

    def record_once(self, decision: Mapping[str, Any]) -> Mapping[str, Any]:
        """Persist once by checkpoint and idempotency identities."""
        ...

    def get_by_checkpoint_id(self, checkpoint_id: str) -> Mapping[str, Any] | None:
        """Return the recorded decision for a checkpoint, if present."""
        ...

    def get_by_idempotency_key(self, key: str) -> Mapping[str, Any] | None:
        """Return the recorded decision for an idempotency identity, if present."""
        ...
