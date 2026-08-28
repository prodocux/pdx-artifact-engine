"""Phase 3 compare/verify worker paths and processing_output result semantics."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from pdx_artifact_engine.jobs import JobStore
from pdx_artifact_engine.jobs.service import JobService
from pdx_artifact_engine.staging import StagingStore
from pdx_artifact_engine.worker import JobWorker

ROOT = Path(__file__).resolve().parents[1]
PHASE0 = ROOT / "docs" / "phase0"
KERNEL_ROOT = ROOT.parent / "prodocux"


def _compare_request() -> dict[str, Any]:
    return json.loads(
        (
            KERNEL_ROOT / "examples" / "contracts" / "normalized_diff_request_v1.json"
        ).read_text(encoding="utf-8")
    )


def _verify_request() -> dict[str, Any]:
    return json.loads(
        (
            KERNEL_ROOT / "examples" / "contracts" / "evidence_bundle_request_v1.json"
        ).read_text(encoding="utf-8")
    )


def _create_body(*, job_id: str, operation: str, request: dict[str, Any]) -> dict:
    raw = json.dumps(request, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return {
        "schema_version": "pdx_internal_job_create_v1",
        "job_id": job_id,
        "operation": operation,
        "subject": {"binding_id": "subject-1", "revision": "rev-1"},
        "input_digest": digest,
        "operation_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "idempotency_key": f"{job_id}:{operation}",
        "correlation_id": "corr-1",
        "request_id": "req-1",
        "deadline_at": "2099-01-01T00:00:00Z",
        "kernel_contract": "v1",
        "payload": {
            "encoding": "base64",
            "media_type": "application/json",
            "filename": "request.json",
            "content_b64": base64.b64encode(raw).decode("ascii"),
            "decoded_size_bytes": len(raw),
        },
    }


class FakeKernel:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.compare_calls = 0
        self.verify_calls = 0
        self.derived_calls = 0

    def materialize_intake(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

    def extract_content_blocks_from_artifact(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

    def render_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def compare_normalized_profiles(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.compare_calls += 1
        if self.compare_calls <= self.fail_times:
            raise RuntimeError("kernel down")
        return {
            "schema_version": "prodocux_normalized_diff_result_v1",
            "verifier_id": "prodocux.normalized_diff",
            "verifier_version": "1",
            "request_digest": hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "status": "changed",
            "before_document_id": payload["before"]["document_id"],
            "after_document_id": payload["after"]["document_id"],
            "before_source_sha256": payload["before"]["source_sha256"],
            "after_source_sha256": payload["after"]["source_sha256"],
            "string_normalization": payload.get("string_normalization", "exact"),
            "changes": [],
            "total_changes": 0,
            "truncated": False,
        }

    def verify_evidence_bundle(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.verify_calls += 1
        if self.verify_calls <= self.fail_times:
            raise RuntimeError("kernel down")
        return {
            "schema_version": "prodocux_evidence_bundle_result_v1",
            "request_id": payload["request_id"],
            "canonical_request_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            "verifier": {"id": "prodocux.evidence", "version": "1"},
            "rule_set": payload["rule_set"],
            "status": "pass",
            "results": [
                {
                    "check_id": payload["checks"][0]["check_id"],
                    "status": "pass",
                    "reason_codes": [],
                    "evidence_ids": [],
                }
            ],
        }

    def store_derived(
        self,
        *,
        output_name: str,
        content_b64: str,
        media_type: str,
        sha256: str | None = None,
    ) -> dict[str, Any]:
        self.derived_calls += 1
        raw = base64.b64decode(content_b64)
        digest = hashlib.sha256(raw).hexdigest()
        if sha256 is not None:
            assert digest == sha256
        artifact_id = hashlib.sha256(f"{output_name}:{digest}".encode()).hexdigest()
        return {
            "schema_version": "prodocux_opaque_artifact_v1",
            "artifact_id": artifact_id,
            "uri": f"artifact://derived/{artifact_id}/{output_name}",
            "sha256": digest,
            "size_bytes": len(raw),
            "media_type": media_type,
        }


def _worker(tmp_path: Path, kernel: FakeKernel) -> tuple[JobService, JobWorker]:
    store = JobStore(tmp_path / "jobs.sqlite3")
    staging = StagingStore(tmp_path / "staging", ttl_seconds=3600)
    service = JobService(store=store, staging=staging, contract_root=PHASE0)
    worker = JobWorker(
        store=store,
        staging=staging,
        service=service,
        kernel=kernel,
        owner="test-worker",
        max_attempts=3,
    )
    return service, worker


@pytest.mark.parametrize(
    ("operation", "kernel_method", "output_name"),
    [
        ("compare_normalized_profiles", "compare_calls", "normalized_diff_result.json"),
        ("verify_evidence", "verify_calls", "evidence_bundle_result.json"),
    ],
)
def test_worker_persists_processing_output_json_artifact(
    tmp_path: Path,
    operation: str,
    kernel_method: str,
    output_name: str,
) -> None:
    request = _compare_request() if operation == "compare_normalized_profiles" else _verify_request()
    service, worker = _worker(tmp_path, FakeKernel())
    body = _create_body(job_id=f"job-{operation}", operation=operation, request=request)
    service.create(body)
    finished = worker.run_once()
    assert finished is not None
    assert finished.state == "completed"
    kernel = worker.kernel
    assert getattr(kernel, kernel_method) == 1
    assert kernel.derived_calls == 1
    status = service.get(body["job_id"])
    assert "content_b64" not in json.dumps(status)
    result = service.get_result(body["job_id"])
    assert result["kind"] == "processing_output"
    assert result["artifact"]["uri"].startswith("artifact://derived/")
    assert result["artifact"]["uri"].endswith(f"/{output_name}")
    assert result["artifact"]["media_type"] == "application/json"


def test_compare_worker_retries_then_completes(tmp_path: Path) -> None:
    service, worker = _worker(tmp_path, FakeKernel(fail_times=1))
    body = _create_body(
        job_id="job-retry-compare",
        operation="compare_normalized_profiles",
        request=_compare_request(),
    )
    service.create(body)
    first = worker.run_once()
    assert first is not None
    assert first.state == "pending"
    second = worker.run_once()
    assert second is not None
    assert second.state == "completed"


def test_verify_worker_respects_cancel_before_finalize(tmp_path: Path) -> None:
    service, worker = _worker(tmp_path, FakeKernel())
    body = _create_body(
        job_id="job-cancel-verify",
        operation="verify_evidence",
        request=_verify_request(),
    )
    _, created = service.create(body)
    handle = created["staging"]["handle"]
    claimed = worker.store.claim_next(owner="test-worker", lease_seconds=60, max_attempts=3)
    assert claimed is not None
    service.cancel(
        body["job_id"],
        {
            "schema_version": "pdx_internal_job_cancel_v1",
            "job_id": body["job_id"],
            "request_id": "req-cancel",
            "correlation_id": body["correlation_id"],
        },
    )
    worker._process(claimed)
    record = worker.store.get(body["job_id"])
    assert record is not None
    assert record.state == "cancelled"
    assert worker.staging.read_bytes(handle) is None
