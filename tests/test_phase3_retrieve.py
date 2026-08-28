"""Phase 3 Engine job-bound verified artifact retrieval."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from pdx_artifact_engine.jobs import JobRecord, JobStore
from pdx_artifact_engine.jobs.service import JobService, JobServiceError
from pdx_artifact_engine.staging import StagingStore

ROOT = Path(__file__).resolve().parents[1]
PHASE0 = ROOT / "docs" / "phase0"
PHASE3 = ROOT / "docs" / "phase3"


def _schema(name: str) -> dict:
    return json.loads((PHASE3 / "schemas" / name).read_text(encoding="utf-8"))


def _item(*, job_id: str, kind: str, uri: str, artifact_id: str) -> dict:
    return {
        "schema_version": "pdx_internal_job_result_v1",
        "job_id": job_id,
        "kind": kind,
        "artifact": {
            "schema_version": "prodocux_opaque_artifact_v1",
            "artifact_id": artifact_id,
            "uri": uri,
            "sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
            "size_bytes": 1,
            "media_type": "application/octet-stream",
        },
    }


class _FakeKernel:
    def retrieve_artifact(self, *, request_id: str, artifact: dict) -> dict:
        return {
            "schema_version": "prodocux_artifact_content_v1",
            "request_id": request_id,
            "artifact": dict(artifact),
            "media_type": artifact["media_type"],
            "size_bytes": artifact["size_bytes"],
            "sha256": artifact["sha256"],
            "content_b64": base64.b64encode(b"a").decode("ascii"),
        }


def _completed_job(
    tmp_path: Path,
    *,
    job_id: str = "job-retrieve-1",
) -> tuple[JobService, dict]:
    store = JobStore(tmp_path / "jobs.sqlite3")
    staging = StagingStore(tmp_path / "staging")
    service = JobService(
        store=store,
        staging=staging,
        contract_root=PHASE0,
        phase3_contract_root=PHASE3,
        kernel=_FakeKernel(),
    )
    artifact_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    record = JobRecord(
        job_id=job_id,
        state="completed",
        document={
            "schema_version": "pdx_internal_job_status_v1",
            "job_id": job_id,
            "operation": "render_artifact",
            "state": "completed",
            "input_digest": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
            "operation_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "idempotency_key": f"{job_id}:render_artifact",
            "correlation_id": "corr-1",
            "request_id": "req-1",
            "kernel_contract": "v1",
        },
        idempotency_key=f"{job_id}:render_artifact",
        operation_digest="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        result=[
            _item(
                job_id=job_id,
                kind="processing_output",
                uri=f"artifact://sink/{artifact_id}/output.docx",
                artifact_id=artifact_id,
            ),
        ],
    )
    store.insert(record)
    artifact = record.result[0]["artifact"]
    return service, artifact


def test_retrieve_schema_accepts_bound_request() -> None:
    validator = Draft202012Validator(
        _schema("pdx_internal_job_artifact_retrieve_v1.schema.json"),
        format_checker=FormatChecker(),
    )
    doc = {
        "schema_version": "pdx_internal_job_artifact_retrieve_v1",
        "job_id": "job-1",
        "kind": "processing_output",
        "request_id": "req-1",
        "correlation_id": "corr-1",
        "artifact": {
            "schema_version": "prodocux_opaque_artifact_v1",
            "artifact_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "uri": "artifact://sink/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/out.docx",
            "sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
            "size_bytes": 1,
            "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    }
    assert list(validator.iter_errors(doc)) == []


def test_service_retrieve_happy_path(tmp_path: Path) -> None:
    service, artifact = _completed_job(tmp_path)
    body = {
        "schema_version": "pdx_internal_job_artifact_retrieve_v1",
        "job_id": "job-retrieve-1",
        "kind": "processing_output",
        "request_id": "req-retrieve",
        "correlation_id": "corr-retrieve",
        "artifact": artifact,
    }
    doc = service.retrieve("job-retrieve-1", body)
    validator = Draft202012Validator(
        _schema("pdx_internal_job_artifact_content_v1.schema.json"),
        format_checker=FormatChecker(),
    )
    assert list(validator.iter_errors(doc)) == []
    assert doc["kind"] == "processing_output"
    assert base64.b64decode(doc["content_b64"]) == b"a"


def test_service_retrieve_binding_mismatch(tmp_path: Path) -> None:
    service, artifact = _completed_job(tmp_path)
    bad = dict(artifact)
    bad["sha256"] = "0000000000000000000000000000000000000000000000000000000000000000"
    body = {
        "schema_version": "pdx_internal_job_artifact_retrieve_v1",
        "job_id": "job-retrieve-1",
        "kind": "processing_output",
        "request_id": "req-retrieve",
        "correlation_id": "corr-retrieve",
        "artifact": bad,
    }
    with pytest.raises(JobServiceError) as excinfo:
        service.retrieve("job-retrieve-1", body)
    assert excinfo.value.code == "ARTIFACT_BINDING_MISMATCH"
    assert excinfo.value.status == 409


def test_service_retrieve_not_ready(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    staging = StagingStore(tmp_path / "staging")
    service = JobService(
        store=store,
        staging=staging,
        contract_root=PHASE0,
        phase3_contract_root=PHASE3,
        kernel=_FakeKernel(),
    )
    body = json.loads(
        (PHASE0 / "examples" / "job_create.intake_document.json").read_text(
            encoding="utf-8"
        )
    )
    service.create(body)
    with pytest.raises(JobServiceError) as excinfo:
        service.retrieve(
            body["job_id"],
            {
                "schema_version": "pdx_internal_job_artifact_retrieve_v1",
                "job_id": body["job_id"],
                "kind": "materialized_source",
                "request_id": "req-1",
                "correlation_id": "corr-1",
                "artifact": {
                    "schema_version": "prodocux_opaque_artifact_v1",
                    "artifact_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "uri": "artifact://intake/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/doc.pdf",
                    "sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                    "size_bytes": 1,
                    "media_type": "application/pdf",
                },
            },
        )
    assert excinfo.value.code == "RESULT_NOT_READY"


def test_service_retrieve_kernel_unconfigured(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    staging = StagingStore(tmp_path / "staging")
    service = JobService(
        store=store,
        staging=staging,
        contract_root=PHASE0,
        phase3_contract_root=PHASE3,
        kernel=None,
    )
    job_id = "job-no-kernel"
    artifact_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    store.insert(
        JobRecord(
            job_id=job_id,
            state="completed",
            document={
                "schema_version": "pdx_internal_job_status_v1",
                "job_id": job_id,
                "operation": "render_artifact",
                "state": "completed",
                "input_digest": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                "operation_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "idempotency_key": f"{job_id}:render_artifact",
                "correlation_id": "c",
                "request_id": "r",
                "kernel_contract": "v1",
            },
            idempotency_key=f"{job_id}:render_artifact",
            operation_digest="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            result=[
                _item(
                    job_id=job_id,
                    kind="processing_output",
                    uri=f"artifact://sink/{artifact_id}/output.docx",
                    artifact_id=artifact_id,
                ),
            ],
        )
    )
    artifact = store.get(job_id).result[0]["artifact"]
    with pytest.raises(JobServiceError) as excinfo:
        service.retrieve(
            job_id,
            {
                "schema_version": "pdx_internal_job_artifact_retrieve_v1",
                "job_id": job_id,
                "kind": "processing_output",
                "request_id": "req-1",
                "correlation_id": "corr-1",
                "artifact": artifact,
            },
        )
    assert excinfo.value.code == "KERNEL_UNAVAILABLE"
    assert excinfo.value.status == 503


def test_service_retrieve_rejects_unverified_kernel_bytes(tmp_path: Path) -> None:
    class TamperedKernel:
        def retrieve_artifact(self, *, request_id: str, artifact: dict) -> dict:
            return {
                "schema_version": "prodocux_artifact_content_v1",
                "request_id": request_id,
                "artifact": dict(artifact),
                "media_type": artifact["media_type"],
                "size_bytes": artifact["size_bytes"],
                "sha256": artifact["sha256"],
                "content_b64": base64.b64encode(b"Z").decode("ascii"),
            }

    service, artifact = _completed_job(tmp_path)
    service.kernel = TamperedKernel()
    with pytest.raises(JobServiceError) as excinfo:
        service.retrieve(
            "job-retrieve-1",
            {
                "schema_version": "pdx_internal_job_artifact_retrieve_v1",
                "job_id": "job-retrieve-1",
                "kind": "processing_output",
                "request_id": "req-1",
                "correlation_id": "corr-1",
                "artifact": artifact,
            },
        )
    assert excinfo.value.code == "KERNEL_RESPONSE_INVALID"


def test_service_retrieve_maps_artifact_too_large(tmp_path: Path) -> None:
    from pdx_adapter_prodocux.http_client import ProDocuXHttpError

    class TooLargeKernel:
        def retrieve_artifact(self, *, request_id: str, artifact: dict) -> dict:
            raise ProDocuXHttpError("Kernel HTTP 413 on artifacts/retrieve", status=413)

    store = JobStore(tmp_path / "jobs.sqlite3")
    staging = StagingStore(tmp_path / "staging")
    service = JobService(
        store=store,
        staging=staging,
        contract_root=PHASE0,
        phase3_contract_root=PHASE3,
        kernel=TooLargeKernel(),
    )
    job_id = "job-too-large"
    artifact_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    store.insert(
        JobRecord(
            job_id=job_id,
            state="completed",
            document={
                "schema_version": "pdx_internal_job_status_v1",
                "job_id": job_id,
                "operation": "render_artifact",
                "state": "completed",
                "input_digest": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                "operation_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "idempotency_key": f"{job_id}:render_artifact",
                "correlation_id": "c",
                "request_id": "r",
                "kernel_contract": "v1",
            },
            idempotency_key=f"{job_id}:render_artifact",
            operation_digest="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            result=[
                _item(
                    job_id=job_id,
                    kind="processing_output",
                    uri=f"artifact://sink/{artifact_id}/output.docx",
                    artifact_id=artifact_id,
                ),
            ],
        )
    )
    artifact = store.get(job_id).result[0]["artifact"]
    with pytest.raises(JobServiceError) as excinfo:
        service.retrieve(
            job_id,
            {
                "schema_version": "pdx_internal_job_artifact_retrieve_v1",
                "job_id": job_id,
                "kind": "processing_output",
                "request_id": "req-1",
                "correlation_id": "corr-1",
                "artifact": artifact,
            },
        )
    assert excinfo.value.code == "ARTIFACT_TOO_LARGE"
    assert excinfo.value.status == 413
    assert excinfo.value.retryable is False


def test_service_retrieve_rejects_unverified_kernel_bytes(tmp_path: Path) -> None:
    class TamperedKernel:
        def retrieve_artifact(self, *, request_id: str, artifact: dict) -> dict:
            return {
                "schema_version": "prodocux_artifact_content_v1",
                "request_id": request_id,
                "artifact": dict(artifact),
                "media_type": artifact["media_type"],
                "size_bytes": artifact["size_bytes"],
                "sha256": artifact["sha256"],
                "content_b64": base64.b64encode(b"Z").decode("ascii"),
            }

    service, artifact = _completed_job(tmp_path)
    service.kernel = TamperedKernel()
    with pytest.raises(JobServiceError) as excinfo:
        service.retrieve(
            "job-retrieve-1",
            {
                "schema_version": "pdx_internal_job_artifact_retrieve_v1",
                "job_id": "job-retrieve-1",
                "kind": "processing_output",
                "request_id": "req-1",
                "correlation_id": "corr-1",
                "artifact": artifact,
            },
        )
    assert excinfo.value.code == "KERNEL_RESPONSE_INVALID"
