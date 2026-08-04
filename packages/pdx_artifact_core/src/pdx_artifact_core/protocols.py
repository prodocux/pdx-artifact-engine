"""Runtime protocols (ToolExecutor, Verifier, StorageAdapter)."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable


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
    def check_id(self) -> str:
        ...

    def verify(
        self,
        check: str,
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Return at least {passed: bool, detail?: str}."""
        ...


@runtime_checkable
class StorageAdapter(Protocol):
    """Resolve opaque artifact URIs; never persist signed URLs or secrets."""

    def resolve(self, uri: str) -> Any:
        ...

    def exists(self, uri: str) -> bool:
        ...
