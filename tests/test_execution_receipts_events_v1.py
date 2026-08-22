from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pdx_artifact_core import (
    CancellationSignal,
    ExecutionContextError,
    ManualCancellationSignal,
    PublicationReceiptError,
    create_execution_context,
    create_publication_receipt,
    ensure_execution_allowed,
    next_execution_attempt,
    run_event,
    run_event_v1,
    validate_execution_context,
    validate_ordered_run_events,
    validate_publication_receipt,
    validate_run_event_v1,
)

ROOT = Path(__file__).resolve().parents[1]


def _example(name: str) -> dict:
    return json.loads((ROOT / "examples/contracts" / name).read_text(encoding="utf-8"))


def test_execution_context_example_and_stable_retry_identities() -> None:
    example = _example("execution_context_v1.json")
    assert validate_execution_context(example) == []
    retried = next_execution_attempt(example, remaining_budget_ms=20_000)
    assert retried["attempt"] == 2
    for field in ("request_id", "correlation_id", "idempotency_key"):
        assert retried[field] == example[field]


def test_cancellation_and_deadline_fail_before_dispatch() -> None:
    context = create_execution_context(
        request_id="request-1",
        correlation_id="correlation-1",
        idempotency_key="request-1:tool",
        deadline_at="2026-08-22T00:00:01Z",
    )
    signal = ManualCancellationSignal()
    assert isinstance(signal, CancellationSignal)
    ensure_execution_allowed(
        context, cancellation=signal, now=datetime(2026, 8, 22, tzinfo=UTC)
    )
    signal.cancel()
    with pytest.raises(ExecutionContextError, match="cancelled"):
        ensure_execution_allowed(context, cancellation=signal)
    with pytest.raises(ExecutionContextError, match="deadline"):
        ensure_execution_allowed(
            context, now=datetime(2026, 8, 22, 0, 0, 2, tzinfo=UTC)
        )


def test_publication_receipt_example_and_digest_semantics() -> None:
    example = _example("publication_receipt_v1.json")
    assert validate_publication_receipt(example) == []
    receipt = create_publication_receipt(
        receipt_id="receipt-2",
        operation_id="operation-2",
        target_id="opaque-target-2",
        request_id="request-2",
        idempotency_key="request-2:publish",
        status="no_op",
        expected_digest="a" * 64,
        observed_digest="a" * 64,
        verifier_id="content.digest",
        verifier_version="1",
        recorded_at="2026-08-22T00:00:00Z",
    )
    assert receipt["status"] == "no_op"
    with pytest.raises(PublicationReceiptError, match="must equal"):
        create_publication_receipt(
            **{
                **{key: value for key, value in receipt.items() if key not in {"schema_version", "observed_digest"}},
                "observed_digest": "b" * 64,
            }
        )


def test_versioned_event_replay_is_ordered_and_existing_event_is_unchanged() -> None:
    first = _example("run_event_v1.json")
    second = run_event_v1(
        event_id="event-run-1-0002",
        run_id=first["run_id"],
        sequence=2,
        occurred_at="2026-08-22T00:00:01Z",
        event_type="RUN_FINISHED",
        request_id=first["request_id"],
        correlation_id=first["correlation_id"],
        idempotency_key=first["idempotency_key"],
        status="completed",
    )
    assert validate_run_event_v1(first) == []
    assert validate_ordered_run_events([first, second]) == []
    legacy = run_event(
        event_type="RUN_STARTED",
        request_id="request-1",
        correlation_id="correlation-1",
        idempotency_key="request-1:run",
        status="started",
    )
    assert "schema_version" not in legacy


def test_event_replay_rejects_duplicates_regression_and_mixed_runs() -> None:
    first = _example("run_event_v1.json")
    duplicate = deepcopy(first)
    duplicate["run_id"] = "another-run"
    errors = validate_ordered_run_events([first, duplicate])
    assert any("multiple runs" in error for error in errors)
    assert any("duplicate identity" in error for error in errors)
    assert any("monotonically" in error for error in errors)
