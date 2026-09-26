from __future__ import annotations

from copy import deepcopy

import pytest
from pdx_artifact_core import (
    ContinuableExtractionError,
    accept_extraction_range,
    create_continuable_extraction,
    validate_continuable_extraction,
)


def _state() -> dict:
    return create_continuable_extraction(
        operation_id="operation-1",
        source_artifact_digest="a" * 64,
        source_sha256="b" * 64,
        media_type="application/pdf",
        parser_contract_name="example_page_projection_v1",
        parser_contract_version="1",
        capability_digest="c" * 64,
        first_range={"unit": "page", "start": 0, "end": 50},
        limits={"ranges": 3, "blocks": 1000, "bytes": 1000000, "retries": 2},
    )


def test_accepts_ordered_ranges_and_exact_replay_is_idempotent() -> None:
    state = _state()
    first = accept_extraction_range(
        state,
        expected_revision=0,
        idempotency_key="range-1",
        request_range={"unit": "page", "start": 0, "end": 50},
        result_artifact_digest="d" * 64,
        result_payload_digest="e" * 64,
        returned_blocks=50,
        returned_bytes=5000,
        next_range={"unit": "page", "start": 50, "end": 55},
        response_range={"unit": "page", "start": 0, "end": 50},
        coverage_disposition="partial_known",
        semantic_validation_digest="9" * 64,
    )
    replay = accept_extraction_range(
        first,
        expected_revision=0,
        idempotency_key="range-1",
        request_range={"unit": "page", "start": 0, "end": 50},
        result_artifact_digest="d" * 64,
        result_payload_digest="e" * 64,
        returned_blocks=50,
        returned_bytes=5000,
        next_range={"unit": "page", "start": 50, "end": 55},
        response_range={"unit": "page", "start": 0, "end": 50},
        coverage_disposition="partial_known",
        semantic_validation_digest="9" * 64,
    )
    assert replay == first
    final = accept_extraction_range(
        first,
        expected_revision=1,
        idempotency_key="range-2",
        request_range={"unit": "page", "start": 50, "end": 55},
        result_artifact_digest="f" * 64,
        result_payload_digest="1" * 64,
        returned_blocks=5,
        returned_bytes=500,
        next_range=None,
        response_range={"unit": "page", "start": 50, "end": 55},
        coverage_disposition="complete",
        semantic_validation_digest="8" * 64,
    )
    assert final["state"] == "completed"
    assert final["consumed"] == {"ranges": 2, "blocks": 55, "bytes": 5500, "retries": 0}


def test_rejects_gap_conflict_stale_revision_and_budget_overrun() -> None:
    state = _state()
    with pytest.raises(ContinuableExtractionError, match="expected next"):
        accept_extraction_range(
            state,
            expected_revision=0,
            idempotency_key="gap",
            request_range={"unit": "page", "start": 51, "end": 55},
            result_artifact_digest="d" * 64,
            result_payload_digest="e" * 64,
            returned_blocks=4,
            returned_bytes=400,
            next_range=None,
        )
    with pytest.raises(ContinuableExtractionError, match="revision conflict"):
        accept_extraction_range(
            state,
            expected_revision=1,
            idempotency_key="stale",
            request_range={"unit": "page", "start": 0, "end": 50},
            result_artifact_digest="d" * 64,
            result_payload_digest="e" * 64,
            returned_blocks=50,
            returned_bytes=5000,
            next_range=None,
        )
    over = deepcopy(state)
    over["consumed"]["bytes"] = over["limits"]["bytes"] + 1
    assert any(
        "exceeds limit" in error for error in validate_continuable_extraction(over)
    )


def test_no_next_descriptor_without_complete_evidence_fails_closed() -> None:
    state = accept_extraction_range(
        _state(),
        expected_revision=0,
        idempotency_key="empty-terminal",
        request_range={"unit": "page", "start": 0, "end": 50},
        result_artifact_digest="d" * 64,
        result_payload_digest="e" * 64,
        returned_blocks=0,
        returned_bytes=0,
        next_range=None,
    )
    assert state["state"] == "failed"
    assert state["terminal_reason"] == "INCOMPLETE_PROJECTION"
    assert state["terminal_coverage"]["disposition"] == "partial_unknown"


def test_earlier_unknown_coverage_cannot_be_erased_by_complete_final_range() -> None:
    first = accept_extraction_range(
        _state(),
        expected_revision=0,
        idempotency_key="range-1",
        request_range={"unit": "page", "start": 0, "end": 50},
        result_artifact_digest="d" * 64,
        result_payload_digest="e" * 64,
        returned_blocks=50,
        returned_bytes=5000,
        next_range={"unit": "page", "start": 50, "end": 55},
        response_range={"unit": "page", "start": 1, "end": 51},
        coverage_disposition="partial_unknown",
        omissions=["ocr_required_not_performed"],
        semantic_validation_digest="9" * 64,
        ocr_disposition="unavailable",
    )
    final = accept_extraction_range(
        first,
        expected_revision=1,
        idempotency_key="range-2",
        request_range={"unit": "page", "start": 50, "end": 55},
        result_artifact_digest="f" * 64,
        result_payload_digest="1" * 64,
        returned_blocks=5,
        returned_bytes=500,
        next_range=None,
        response_range={"unit": "page", "start": 51, "end": 56},
        coverage_disposition="complete",
        omissions=[],
        semantic_validation_digest="8" * 64,
        ocr_disposition="not_evaluated",
    )
    assert final["state"] == "failed"
    assert final["terminal_coverage"] == {
        "disposition": "partial_unknown",
        "omissions": ["ocr_required_not_performed"],
        "ocr_disposition": "unavailable",
    }
