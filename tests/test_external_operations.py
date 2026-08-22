from __future__ import annotations

import json
from pathlib import Path

import pytest
from pdx_artifact_core import (
    ExternalOperationError,
    RunState,
    create_external_operation,
    external_operation_retry_allowed,
    external_operation_run_state,
    transition_external_operation,
    validate_external_operation,
)

ROOT = Path(__file__).resolve().parents[1]


def _operation() -> dict:
    return create_external_operation(
        operation_id="opaque-operation-1",
        provider="document.processor",
        execution_mode="asynchronous",
        request_id="request-1",
        idempotency_key="request-1:extract",
        request_digest="a" * 64,
        input_digest="b" * 64,
        submitted_at="2026-08-22T00:00:00Z",
    )


def test_example_and_pending_operation_map_to_awaiting_tool() -> None:
    example = json.loads(
        (ROOT / "examples/contracts/external_operation_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert validate_external_operation(example) == []
    assert external_operation_run_state(example) is RunState.AWAITING_TOOL


def test_completed_transition_preserves_identities_and_resumes_runtime() -> None:
    submitted = _operation()
    pending = transition_external_operation(
        submitted, status="pending", updated_at="2026-08-22T00:00:01Z"
    )
    completed = transition_external_operation(
        pending,
        status="completed",
        updated_at="2026-08-22T00:00:02Z",
        output_digest="c" * 64,
    )
    for field in (
        "operation_id",
        "provider",
        "request_id",
        "idempotency_key",
        "request_digest",
        "input_digest",
    ):
        assert completed[field] == submitted[field]
    assert external_operation_run_state(completed) is RunState.RUNNING


def test_unknown_outcome_requires_reconciliation_and_forbids_retry() -> None:
    unknown = transition_external_operation(
        _operation(),
        status="unknown_outcome",
        updated_at="2026-08-22T00:00:02Z",
        error={
            "code": "OUTCOME_UNKNOWN",
            "message": "The host must reconcile the opaque operation.",
            "retryable": False,
        },
        reconcile_required=True,
    )
    assert external_operation_run_state(unknown) is RunState.BLOCKED
    assert not external_operation_retry_allowed(unknown)
    with pytest.raises(ExternalOperationError):
        transition_external_operation(
            _operation(),
            status="unknown_outcome",
            updated_at="2026-08-22T00:00:02Z",
            error={
                "code": "OUTCOME_UNKNOWN",
                "message": "unsafe retry",
                "retryable": True,
            },
            reconcile_required=False,
        )


def test_failure_retry_requires_explicit_safe_signal() -> None:
    failed = transition_external_operation(
        _operation(),
        status="failed",
        updated_at="2026-08-22T00:00:02Z",
        error={"code": "REMOTE_REJECTED", "message": "rejected", "retryable": True},
    )
    assert external_operation_retry_allowed(failed)


def test_timestamp_regression_and_secret_fields_fail_closed() -> None:
    operation = _operation()
    operation["updated_at"] = "2026-08-21T23:59:59Z"
    assert any("must not precede" in error for error in validate_external_operation(operation))
    operation = _operation()
    operation["access_token"] = "secret"
    assert validate_external_operation(operation)
