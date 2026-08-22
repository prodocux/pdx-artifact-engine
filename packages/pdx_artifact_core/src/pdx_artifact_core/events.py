"""Product-neutral run-event contracts and reference sink."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from pdx_artifact_core.validate import load_schema


class RunEventError(ValueError):
    """A versioned run event or ordered replay failed closed."""


def run_event(
    *,
    event_type: str,
    request_id: str,
    correlation_id: str,
    idempotency_key: str,
    status: str,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not all((event_type, request_id, correlation_id, idempotency_key, status)):
        raise ValueError("run event identity fields must be non-empty")
    bounded = dict(detail or {})
    if len(bounded) > 20 or not all(
        value is None or isinstance(value, (str, int, float, bool))
        for value in bounded.values()
    ):
        raise ValueError("run event detail must contain at most 20 scalar fields")
    return {
        "event_type": event_type,
        "request_id": request_id,
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
        "status": status,
        "detail": bounded,
    }


def validate_run_event_v1(event: Mapping[str, Any]) -> list[str]:
    """Validate an additive versioned run event without changing ``run_event``."""
    validator = Draft202012Validator(
        load_schema("run_event.v1.schema.json"),
        format_checker=FormatChecker(),
    )
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(event), key=lambda item: list(item.path))
    ]


def run_event_v1(
    *,
    event_id: str,
    run_id: str,
    sequence: int,
    occurred_at: str,
    event_type: str,
    request_id: str,
    correlation_id: str,
    idempotency_key: str,
    status: str,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a validated host-sequenced event for durable projections."""
    event = {
        "schema_version": "pdx_run_event_v1",
        "event_id": event_id,
        "run_id": run_id,
        "sequence": sequence,
        "occurred_at": occurred_at,
        "event_type": event_type,
        "request_id": request_id,
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
        "status": status,
        "detail": deepcopy(dict(detail or {})),
    }
    errors = validate_run_event_v1(event)
    if errors:
        raise RunEventError("invalid run event:\n" + "\n".join(errors))
    return event


def validate_ordered_run_events(events: list[Mapping[str, Any]]) -> list[str]:
    """Validate a single-run monotonic stream and replay-safe event identities."""
    errors: list[str] = []
    event_ids: set[str] = set()
    run_id: str | None = None
    previous_sequence: int | None = None
    for index, event in enumerate(events):
        event_errors = validate_run_event_v1(event)
        errors.extend(f"events/{index}/{error}" for error in event_errors)
        if event_errors:
            continue
        if run_id is None:
            run_id = str(event["run_id"])
        elif event["run_id"] != run_id:
            errors.append(f"events/{index}/run_id: stream contains multiple runs")
        event_id = str(event["event_id"])
        if event_id in event_ids:
            errors.append(f"events/{index}/event_id: duplicate identity")
        event_ids.add(event_id)
        sequence = int(event["sequence"])
        if previous_sequence is not None and sequence <= previous_sequence:
            errors.append(f"events/{index}/sequence: must increase monotonically")
        previous_sequence = sequence
    return errors


class InMemoryEventSink:
    """Reference event sink for tests and embedded hosts."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event: Mapping[str, Any]) -> None:
        self.events.append(deepcopy(dict(event)))
