"""Bounded execution context and cooperative cancellation conventions."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from jsonschema import Draft202012Validator, FormatChecker

from pdx_artifact_core.validate import load_schema


class ExecutionContextError(ValueError):
    """Execution context is invalid, cancelled, or out of budget."""


@runtime_checkable
class CancellationSignal(Protocol):
    """Host-supplied cooperative cancellation without runtime coupling."""

    def is_cancelled(self) -> bool: ...


class ManualCancellationSignal:
    """Thread-safe reference signal for embedded hosts and conformance tests."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


def validate_execution_context(context: Mapping[str, Any]) -> list[str]:
    validator = Draft202012Validator(
        load_schema("execution_context.v1.schema.json"),
        format_checker=FormatChecker(),
    )
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(
            validator.iter_errors(context), key=lambda item: list(item.path)
        )
    ]


def create_execution_context(
    *,
    request_id: str,
    correlation_id: str,
    idempotency_key: str,
    attempt: int = 1,
    deadline_at: str | None = None,
    remaining_budget_ms: int | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "schema_version": "pdx_execution_context_v1",
        "request_id": request_id,
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
        "attempt": attempt,
    }
    if deadline_at is not None:
        context["deadline_at"] = deadline_at
    if remaining_budget_ms is not None:
        context["remaining_budget_ms"] = remaining_budget_ms
    if detail is not None:
        context["detail"] = deepcopy(dict(detail))
    errors = validate_execution_context(context)
    if errors:
        raise ExecutionContextError("invalid execution context:\n" + "\n".join(errors))
    return context


def ensure_execution_allowed(
    context: Mapping[str, Any],
    *,
    cancellation: CancellationSignal | None = None,
    now: datetime | None = None,
) -> None:
    """Fail before dispatch when cancellation or a deadline is already effective."""
    errors = validate_execution_context(context)
    if errors:
        raise ExecutionContextError("invalid execution context:\n" + "\n".join(errors))
    if cancellation is not None and cancellation.is_cancelled():
        raise ExecutionContextError("execution was cancelled by the host")
    if context.get("remaining_budget_ms") == 0:
        raise ExecutionContextError("execution budget is exhausted")
    if "deadline_at" in context:
        current = now or datetime.now(UTC)
        deadline = datetime.fromisoformat(str(context["deadline_at"]))
        if current >= deadline:
            raise ExecutionContextError("execution deadline has elapsed")


def next_execution_attempt(
    context: Mapping[str, Any], *, remaining_budget_ms: int | None = None
) -> dict[str, Any]:
    """Advance only the attempt/budget while preserving stable identities."""
    errors = validate_execution_context(context)
    if errors:
        raise ExecutionContextError("invalid execution context:\n" + "\n".join(errors))
    result = deepcopy(dict(context))
    result["attempt"] += 1
    if remaining_budget_ms is not None:
        result["remaining_budget_ms"] = remaining_budget_ms
    errors = validate_execution_context(result)
    if errors:
        raise ExecutionContextError("invalid execution context:\n" + "\n".join(errors))
    return result
