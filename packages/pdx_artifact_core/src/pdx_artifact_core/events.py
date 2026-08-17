"""Product-neutral run-event contracts and reference sink."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


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


class InMemoryEventSink:
    """Reference event sink for tests and embedded hosts."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event: Mapping[str, Any]) -> None:
        self.events.append(deepcopy(dict(event)))
