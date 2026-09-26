from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from pdx_artifact_core import (
    ContinuableExtractionError,
    create_continuable_extraction,
    validate_continuable_extraction_receipt,
)
from pdx_artifact_engine.continuable_extraction import (
    ContinuableExtractionService,
    ContinuableExtractionStore,
)
from pdx_artifact_engine.internal_http import make_server


def _state(operation_id: str = "operation-1") -> dict:
    return create_continuable_extraction(
        operation_id=operation_id,
        source_artifact_digest="a" * 64,
        source_sha256="b" * 64,
        media_type="application/pdf",
        parser_contract_name="example_page_projection_v1",
        parser_contract_version="1",
        capability_digest="c" * 64,
        first_range={"unit": "page", "start": 0, "end": 50},
        limits={"ranges": 3, "blocks": 1000, "bytes": 1000000, "retries": 2},
    )


def _range(**overrides: object) -> dict:
    values = {
        "expected_revision": 0,
        "idempotency_key": "range-1",
        "request_range": {"unit": "page", "start": 0, "end": 50},
        "result_artifact_digest": "d" * 64,
        "result_payload_digest": "e" * 64,
        "returned_blocks": 50,
        "returned_bytes": 5000,
        "next_range": {"unit": "page", "start": 50, "end": 55},
        "response_range": {"unit": "page", "start": 0, "end": 50},
        "coverage_disposition": "partial_known",
        "omissions": [],
        "semantic_validation_digest": "9" * 64,
    }
    values.update(overrides)
    return values


def _service(
    path: Path,
) -> tuple[ContinuableExtractionStore, ContinuableExtractionService]:
    store = ContinuableExtractionStore(path)
    return store, ContinuableExtractionService(store)


def test_restart_recovers_state_and_reconciles_staged_range(tmp_path: Path) -> None:
    path = tmp_path / "extraction.sqlite3"
    store, service = _service(path)
    service.create(_state())
    service.stage_range("operation-1", **_range())
    store.close()

    reopened, recovered = _service(path)
    result = recovered.reconcile("operation-1")
    assert result["revision"] == 1
    assert result["next_range_descriptor"] == {"unit": "page", "start": 50, "end": 55}
    reopened.close()


def test_exact_replay_is_stable_and_conflicting_stage_is_rejected(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "extraction.sqlite3")
    service.create(_state())
    first = service.accept_range("operation-1", **_range())
    replay = service.accept_range("operation-1", **_range())
    assert replay == first
    with pytest.raises(ContinuableExtractionError, match="conflicts with staged"):
        service.stage_range("operation-1", **_range(result_payload_digest="f" * 64))
    store.close()


def test_stale_cas_cancel_timeout_and_terminal_receipts(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "extraction.sqlite3")
    service.create(_state("cancelled-operation"))
    cancelled = service.cancel("cancelled-operation", expected_revision=0)
    assert cancelled["state"] == "cancelled"
    assert service.receipt("cancelled-operation")["terminal_reason"] == "CANCELLED"
    with pytest.raises(ContinuableExtractionError, match="terminal extraction"):
        service.accept_range("cancelled-operation", **_range())

    service.create(_state("timed-operation"))
    with pytest.raises(ContinuableExtractionError, match="revision conflict"):
        service.time_out("timed-operation", expected_revision=1)
    timed = service.time_out("timed-operation", expected_revision=0)
    assert timed["state"] == "timed_out"
    assert service.receipt("timed-operation")["receipt_digest"]
    store.close()


def test_completed_receipt_binds_ordered_ranges_and_counters(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "extraction.sqlite3")
    service.create(_state())
    service.accept_range("operation-1", **_range())
    final = service.accept_range(
        "operation-1",
        **_range(
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
        ),
    )
    receipt = service.receipt("operation-1")
    assert final["state"] == "completed"
    assert receipt["state"] == "completed"
    assert receipt["coverage"] == "complete"
    assert receipt["consumed"] == {
        "ranges": 2,
        "blocks": 55,
        "bytes": 5500,
        "retries": 0,
    }
    assert len(receipt["accepted_ranges_digest"]) == 64
    assert validate_continuable_extraction_receipt(receipt) == []
    store.close()


def test_two_connections_cannot_accept_the_same_revision_twice(tmp_path: Path) -> None:
    path = tmp_path / "extraction.sqlite3"
    store_a, service_a = _service(path)
    service_a.create(_state())
    store_b, service_b = _service(path)
    service_a.stage_range("operation-1", **_range(idempotency_key="worker-a"))
    service_b.stage_range("operation-1", **_range(idempotency_key="worker-b"))

    accepted = service_a.accept_staged("operation-1", "worker-a")
    assert accepted["revision"] == 1
    with pytest.raises(ContinuableExtractionError, match="revision conflict"):
        service_b.accept_staged("operation-1", "worker-b")
    assert service_b.get("operation-1") == accepted
    store_b.close()
    store_a.close()


def test_retry_budget_and_stable_failure_reason_are_terminal(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "extraction.sqlite3")
    state = _state()
    state["limits"]["retries"] = 1
    service.create(state)
    retried = service.record_retry("operation-1", expected_revision=0)
    assert retried["consumed"]["retries"] == 1
    exhausted = service.record_retry("operation-1", expected_revision=1)
    assert exhausted["state"] == "failed"
    assert exhausted["terminal_reason"] == "RETRY_BUDGET_EXHAUSTED"
    assert service.receipt("operation-1")["coverage"] == "partial_unknown"

    service.create(_state("oversized-operation"))
    failed = service.fail(
        "oversized-operation", expected_revision=0, reason="SOURCE_TOO_LARGE"
    )
    assert failed["state"] == "failed"
    with pytest.raises(ContinuableExtractionError, match="uppercase stable code"):
        service.fail("oversized-operation", expected_revision=1, reason="not stable")
    store.close()


def test_private_http_exposes_durable_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "continuable-extraction-test-token"
    monkeypatch.setenv("PDX_ENGINE_AUTH_PROFILE", "self_hosted")
    monkeypatch.setenv("PDX_ENGINE_BEARER_TOKENS", token)

    class Kernel:
        def projection_capabilities(self) -> dict:
            return {"schema_version": "prodocux_projection_capabilities_v1"}

    monkeypatch.setattr(
        "pdx_adapter_prodocux.verified_projection.validate_kernel_projection_capabilities",
        lambda _value: None,
    )
    server = make_server(
        host="127.0.0.1",
        port=0,
        db_path=tmp_path / "http.sqlite3",
        staging_root=tmp_path / "staging",
        kernel=Kernel(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {token}"}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        value = urllib.request.Request(
            base + path, data=payload, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(value) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    try:
        create_request = _state()
        del create_request["capability_digest"]
        del create_request["capability_authority"]
        del create_request["capability_verified"]
        assert request("POST", "/internal/v1/continuable-extractions", create_request)[0] == 202
        status, _first = request(
            "POST", "/internal/v1/continuable-extractions/operation-1/ranges", _range()
        )
        assert status == 404
        status, current = request(
            "GET", "/internal/v1/continuable-extractions/operation-1"
        )
        assert (status, current["state"], current["revision"]) == (200, "pending", 0)
        assert current["capability_authority"] == "kernel_adapter"
        assert current["capability_verified"] is True
        assert current["capability_digest"] != "c" * 64
        assert (
            request(
                "POST",
                "/internal/v1/continuable-extractions/operation-1/ranges/range-1/accept",
                {},
            )[0]
            == 404
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "descriptor",
    [
        {"unit": "page", "start": 1, "end": 51},
        {"unit": "row", "start": 0, "end": 500},
        {"unit": "worksheet_row", "sheet_index": 0, "sheet_name": "Sheet1", "start": 1, "end": 501},
        {"unit": "slide", "start": 1, "end": 51},
        {"unit": "tile", "tile_edge": 512, "start": 0, "end": 16},
    ],
)
def test_durable_engine_is_format_neutral_across_kernel_ranges(
    tmp_path: Path, descriptor: dict
) -> None:
    operation_id = f"operation-{descriptor['unit']}"
    state = create_continuable_extraction(
        operation_id=operation_id,
        source_artifact_digest="a" * 64,
        source_sha256="b" * 64,
        media_type="application/octet-stream",
        parser_contract_name=f"example_{descriptor['unit']}_projection_v1",
        parser_contract_version="1",
        capability_digest="c" * 64,
        first_range=descriptor,
        limits={"ranges": 2, "blocks": 1000, "bytes": 1000000, "retries": 1},
    )
    path = tmp_path / f"{descriptor['unit']}.sqlite3"
    store, service = _service(path)
    service.create(state)
    service.stage_range(
        operation_id,
        expected_revision=0,
        idempotency_key="range-1",
        request_range=descriptor,
        result_artifact_digest="d" * 64,
        result_payload_digest="e" * 64,
        returned_blocks=1,
        returned_bytes=100,
        next_range=None,
        response_range=descriptor,
        coverage_disposition="complete",
        semantic_validation_digest="9" * 64,
    )
    store.close()
    reopened, recovered = _service(path)
    final = recovered.reconcile(operation_id)
    assert final["state"] == "completed"
    assert recovered.receipt(operation_id)["coverage"] == "complete"
    reopened.close()


def test_runner_derives_terminal_state_only_from_validated_kernel_response(
    tmp_path: Path,
) -> None:
    response = {
        "schema_version": "prodocux_pdf_continuable_projection_v1",
        "source_sha256": "b" * 64,
        "parser_contract": {"name": "example_page_projection_v1", "version": "1"},
        "range": {"unit": "page", "start": 1, "end": 2, "requested_max_pages": 50},
        "pages": [{"page_number": 1, "text": "verified", "ocr_required": False}],
        "next_cursor": None,
        "ocr": {"requested": False, "disposition": "not_performed", "pages_requiring_ocr": []},
        "coverage": {"disposition": "complete", "known_total_pages": 1, "continuation_available": False, "omitted_content_classes": []},
        "counts": {"returned_pages": 1, "returned_characters": 8},
    }

    class Kernel:
        def continue_projection(self, **_: object) -> dict:
            return response

        def store_derived(self, *, content_b64: str, media_type: str, **_: object) -> dict:
            import base64

            raw = base64.b64decode(content_b64)
            return {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "media_type": media_type,
            }

    validated: list[str] = []

    def validate(value: dict) -> None:
        validated.append(value["schema_version"])

    store = ContinuableExtractionStore(tmp_path / "runner.sqlite3")
    service = ContinuableExtractionService(
        store, kernel=Kernel(), projection_validator=validate
    )
    state = _state()
    state["next_range_descriptor"] = {"continuation_descriptor": None}
    from pdx_artifact_core import canonical_digest

    state["next_range_digest"] = canonical_digest(state["next_range_descriptor"])
    service.create(state)
    final = service.execute_next(
        "operation-1",
        expected_revision=0,
        idempotency_key="runner-range-1",
        format_name="pdf",
        document_b64="JVBERi0=",
        document_filename="source.pdf",
        range_limit=50,
    )
    assert validated == ["prodocux_pdf_continuable_projection_v1"]
    assert final["state"] == "completed"
    receipt = service.receipt("operation-1")
    assert receipt["coverage"] == "complete"
    assert receipt["aggregate_artifact_digest"] == final["aggregate_artifact_digest"]
    store.close()


def test_incomplete_ocr_terminal_evidence_is_preserved_in_receipt(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "ocr.sqlite3")
    service.create(_state())
    final = service.accept_range(
        "operation-1",
        **_range(
            next_range=None,
            response_range={"unit": "page", "start": 1, "end": 2},
            returned_blocks=1,
            coverage_disposition="partial_unknown",
            omissions=["ocr_required_not_performed"],
            semantic_validation_digest="8" * 64,
            ocr_disposition="unavailable",
        ),
    )
    assert final["state"] == "failed"
    receipt = service.receipt("operation-1")
    assert receipt["coverage"] == "partial_unknown"
    assert receipt["omissions"] == ["ocr_required_not_performed"]
    assert receipt["ocr_disposition"] == "unavailable"
    store.close()


def _accept_partial_unknown(service: ContinuableExtractionService) -> None:
    service.create(_state())
    service.accept_range(
        "operation-1",
        **_range(
            coverage_disposition="partial_unknown",
            omissions=["ocr_required_not_performed"],
            ocr_disposition="not_performed",
        ),
    )


def _assert_preserved_terminal_receipt(
    service: ContinuableExtractionService, expected_omission: str
) -> None:
    receipt = service.receipt("operation-1")
    assert receipt["coverage"] == "partial_unknown"
    assert set(receipt["omissions"]) == {
        "ocr_required_not_performed",
        expected_omission,
    }
    assert receipt["ocr_disposition"] == "not_performed"


def test_cancel_preserves_accumulated_coverage_evidence(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "cancel-evidence.sqlite3")
    _accept_partial_unknown(service)
    service.cancel("operation-1", expected_revision=1)
    _assert_preserved_terminal_receipt(service, "cancelled_before_completion")
    store.close()


def test_timeout_preserves_accumulated_coverage_evidence(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "timeout-evidence.sqlite3")
    _accept_partial_unknown(service)
    service.time_out("operation-1", expected_revision=1)
    _assert_preserved_terminal_receipt(service, "time_limit_exhausted")
    store.close()


def test_retry_exhaustion_preserves_accumulated_coverage_evidence(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "retry-evidence.sqlite3")
    _accept_partial_unknown(service)
    first = service.record_retry("operation-1", expected_revision=1)
    second = service.record_retry("operation-1", expected_revision=first["revision"])
    service.record_retry("operation-1", expected_revision=second["revision"])
    _assert_preserved_terminal_receipt(service, "retry_budget_exhausted")
    store.close()


def test_source_too_large_preserves_accumulated_coverage_evidence(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "source-evidence.sqlite3")
    _accept_partial_unknown(service)
    service.fail("operation-1", expected_revision=1, reason="SOURCE_TOO_LARGE")
    _assert_preserved_terminal_receipt(service, "source_too_large")
    store.close()
