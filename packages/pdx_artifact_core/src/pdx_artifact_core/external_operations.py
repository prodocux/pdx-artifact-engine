"""Product-neutral lifecycle for durable external operations."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from pdx_artifact_core.state import RunState
from pdx_artifact_core.validate import load_schema

_TRANSITIONS = {
    "submitted": frozenset({"pending", "completed", "failed", "timed_out", "cancelled", "unknown_outcome"}),
    "pending": frozenset({"pending", "completed", "failed", "timed_out", "cancelled", "unknown_outcome"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "timed_out": frozenset({"unknown_outcome"}),
    "cancelled": frozenset(),
    "unknown_outcome": frozenset({"completed", "failed", "cancelled"}),
}


class ExternalOperationError(ValueError):
    """An external-operation contract or transition failed closed."""


def _validator() -> Draft202012Validator:
    artifact_schema = load_schema("artifact_storage_identity.v1.schema.json")
    registry = Registry().with_resource(
        artifact_schema["$id"], Resource.from_contents(artifact_schema)
    )
    return Draft202012Validator(
        load_schema("external_operation.v1.schema.json"),
        registry=registry,
        format_checker=FormatChecker(),
    )


def validate_external_operation(operation: Mapping[str, Any]) -> list[str]:
    """Validate schema and monotonic timestamps."""
    errors = [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(
            _validator().iter_errors(operation), key=lambda item: list(item.path)
        )
    ]
    if errors:
        return errors
    submitted = datetime.fromisoformat(operation["submitted_at"])
    updated = datetime.fromisoformat(operation["updated_at"])
    if updated < submitted:
        errors.append("updated_at: must not precede submitted_at")
    return errors


def create_external_operation(
    *,
    operation_id: str,
    provider: str,
    execution_mode: str,
    request_id: str,
    idempotency_key: str,
    request_digest: str,
    input_digest: str,
    submitted_at: str,
    status: str = "submitted",
) -> dict[str, Any]:
    """Create a validated initial external-operation envelope."""
    operation = {
        "schema_version": "pdx_external_operation_v1",
        "operation_id": operation_id,
        "provider": provider,
        "execution_mode": execution_mode,
        "status": status,
        "request_id": request_id,
        "idempotency_key": idempotency_key,
        "request_digest": request_digest,
        "input_digest": input_digest,
        "submitted_at": submitted_at,
        "updated_at": submitted_at,
        "reconcile_required": False,
    }
    errors = validate_external_operation(operation)
    if errors:
        raise ExternalOperationError("invalid external operation:\n" + "\n".join(errors))
    return operation


def transition_external_operation(
    operation: Mapping[str, Any],
    *,
    status: str,
    updated_at: str,
    output_digest: str | None = None,
    artifacts: list[Mapping[str, Any]] | None = None,
    error: Mapping[str, Any] | None = None,
    reconcile_required: bool = False,
) -> dict[str, Any]:
    """Return a validated lifecycle update while preserving stable identities."""
    current_errors = validate_external_operation(operation)
    if current_errors:
        raise ExternalOperationError(
            "invalid external operation:\n" + "\n".join(current_errors)
        )
    current = str(operation["status"])
    if status not in _TRANSITIONS[current]:
        raise ExternalOperationError(f"invalid external operation transition: {current} -> {status}")
    result = deepcopy(dict(operation))
    result["status"] = status
    result["updated_at"] = updated_at
    result["reconcile_required"] = reconcile_required
    for field in ("output_digest", "artifacts", "error"):
        result.pop(field, None)
    if output_digest is not None:
        result["output_digest"] = output_digest
    if artifacts is not None:
        result["artifacts"] = deepcopy([dict(item) for item in artifacts])
    if error is not None:
        result["error"] = deepcopy(dict(error))
    errors = validate_external_operation(result)
    if errors:
        raise ExternalOperationError("invalid external operation:\n" + "\n".join(errors))
    return result


def external_operation_run_state(operation: Mapping[str, Any]) -> RunState:
    """Map external lifecycle status onto the existing run state machine."""
    errors = validate_external_operation(operation)
    if errors:
        raise ExternalOperationError("invalid external operation:\n" + "\n".join(errors))
    return {
        "submitted": RunState.AWAITING_TOOL,
        "pending": RunState.AWAITING_TOOL,
        "completed": RunState.RUNNING,
        "failed": RunState.FAILED,
        "timed_out": RunState.TIMED_OUT,
        "cancelled": RunState.CANCELLED,
        "unknown_outcome": RunState.BLOCKED,
    }[operation["status"]]


def external_operation_retry_allowed(operation: Mapping[str, Any]) -> bool:
    """Allow retry only for an explicit terminal error marked retryable."""
    errors = validate_external_operation(operation)
    if errors:
        raise ExternalOperationError("invalid external operation:\n" + "\n".join(errors))
    error = operation.get("error") or {}
    return operation["status"] in {"failed", "timed_out"} and bool(
        error.get("retryable")
    ) and not operation["reconcile_required"]
