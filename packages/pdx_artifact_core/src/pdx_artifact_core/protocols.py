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
