"""Phase 1 `/results` semantic locks (kind↔URI, uniqueness, job binding)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, RefResolver

from pdx_artifact_engine.jobs import JobRecord, JobStore
from pdx_artifact_engine.jobs.result_contract import (
    ResultContractError,
    validate_result_item,
    validate_result_items,
)
from pdx_artifact_engine.jobs.service import JobService, JobServiceError
from pdx_artifact_engine.staging import StagingStore

ROOT = Path(__file__).resolve().parents[1]
PHASE0 = ROOT / "docs" / "phase0"
PHASE1 = ROOT / "docs" / "phase1"


def _schema(name: str) -> dict:
    return json.loads((PHASE1 / "schemas" / name).read_text(encoding="utf-8"))


def _validator(schema: dict) -> Draft202012Validator:
    store = {
        schema["$id"]: schema
        for schema in (
            _schema("pdx_internal_job_result_v1.schema.json"),
            _schema("pdx_internal_job_results_v1.schema.json"),
        )
    }
    resolver = RefResolver.from_schema(schema, store=store)
    return Draft202012Validator(
        schema, format_checker=FormatChecker(), resolver=resolver
    )


def _item(*, job_id: str, kind: str, uri: str) -> dict:
    return {
        "schema_version": "pdx_internal_job_result_v1",
        "job_id": job_id,
        "kind": kind,
        "artifact": {
            "schema_version": "prodocux_opaque_artifact_v1",
            "artifact_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "uri": uri,
            "sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
            "size_bytes": 1,
            "media_type": "application/octet-stream",
        },
    }


def test_schema_rejects_kind_uri_mismatch() -> None:
    validator = _validator(_schema("pdx_internal_job_result_v1.schema.json"))
    bad_source = _item(
        job_id="job-1",
        kind="materialized_source",
        uri="artifact://derived/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/x.json",
    )
    bad_output = _item(
        job_id="job-1",
        kind="processing_output",
        uri="artifact://intake/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/doc.pdf",
    )
    assert list(validator.iter_errors(bad_source))
    assert list(validator.iter_errors(bad_output))


def test_schema_accepts_bound_kinds() -> None:
    validator = _validator(_schema("pdx_internal_job_result_v1.schema.json"))
    source = _item(
        job_id="job-1",
        kind="materialized_source",
        uri="artifact://intake/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/doc.pdf",
    )
    derived = _item(
        job_id="job-1",
        kind="processing_output",
        uri="artifact://derived/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/content_blocks.json",
    )
    sink = _item(
        job_id="job-1",
        kind="processing_output",
        uri="artifact://sink/records.csv",
    )
    assert list(validator.iter_errors(source)) == []
    assert list(validator.iter_errors(derived)) == []
    assert list(validator.iter_errors(sink)) == []


def test_service_validation_rejects_duplicate_kind_and_job_id_mismatch() -> None:
    with pytest.raises(ResultContractError, match="duplicate"):
        validate_result_items(
            [
                _item(
                    job_id="job-1",
                    kind="processing_output",
                    uri="artifact://sink/a.bin",
                ),
                _item(
                    job_id="job-1",
                    kind="processing_output",
                    uri="artifact://sink/b.bin",
                ),
            ],
            job_id="job-1",
        )
    with pytest.raises(ResultContractError, match="job_id"):
        validate_result_item(
            _item(
                job_id="other",
                kind="processing_output",
                uri="artifact://sink/a.bin",
            ),
            job_id="job-1",
        )


def test_get_results_empty_when_incomplete(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    staging = StagingStore(tmp_path / "staging")
    service = JobService(store=store, staging=staging, contract_root=PHASE0)
    body = json.loads(
        (PHASE0 / "examples" / "job_create.intake_document.json").read_text(
            encoding="utf-8"
        )
    )
    body["deadline_at"] = "2099-01-01T00:00:00Z"
    service.create(body)
    envelope = service.get_results(body["job_id"])
    assert envelope == {
        "schema_version": "pdx_internal_job_results_v1",
        "job_id": body["job_id"],
        "results": [],
    }
    with pytest.raises(JobServiceError) as excinfo:
        service.get_result(body["job_id"])
    assert excinfo.value.code == "RESULT_NOT_READY"


def test_store_refuses_invalid_result_persist(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    record = JobRecord(
        job_id="job-bad",
        state="completed",
        document={
            "schema_version": "pdx_internal_job_status_v1",
            "job_id": "job-bad",
            "operation": "intake_document",
            "state": "completed",
            "input_digest": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
            "operation_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "idempotency_key": "job-bad:intake_document",
            "correlation_id": "c",
            "request_id": "r",
            "kernel_contract": "v1",
        },
        idempotency_key="job-bad:intake_document",
        operation_digest="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        result=_item(
            job_id="job-bad",
            kind="materialized_source",
            uri="artifact://derived/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/x.json",
        ),
    )
    with pytest.raises(ResultContractError, match="URI namespace"):
        store.insert(record)


def test_order_is_non_semantic_consumer_selects_by_kind(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    staging = StagingStore(tmp_path / "staging")
    service = JobService(store=store, staging=staging, contract_root=PHASE0)
    job_id = "job-order-1"
    record = JobRecord(
        job_id=job_id,
        state="completed",
        document={
            "schema_version": "pdx_internal_job_status_v1",
            "job_id": job_id,
            "operation": "intake_document",
            "state": "completed",
            "input_digest": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
            "operation_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "idempotency_key": f"{job_id}:intake_document",
            "correlation_id": "c",
            "request_id": "r",
            "kernel_contract": "v1",
        },
        idempotency_key=f"{job_id}:intake_document",
        operation_digest="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        # Deliberately reverse order vs worker default.
        result=[
            _item(
                job_id=job_id,
                kind="processing_output",
                uri="artifact://derived/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/content_blocks.json",
            ),
            _item(
                job_id=job_id,
                kind="materialized_source",
                uri="artifact://intake/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/doc.pdf",
            ),
        ],
    )
    store.insert(record)
    results = service.get_results(job_id)
    by_kind = {item["kind"]: item for item in results["results"]}
    assert set(by_kind) == {"materialized_source", "processing_output"}
    assert service.get_result(job_id)["kind"] == "materialized_source"
    assert list(
        _validator(_schema("pdx_internal_job_results_v1.schema.json")).iter_errors(
            results
        )
    ) == []
