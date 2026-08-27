"""Phase 1 dock slice: reconcile + worker → Kernel intake hop."""

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


def _example(name: str) -> dict:
    return json.loads((PHASE0 / "examples" / name).read_text(encoding="utf-8"))


def _live_create_body() -> dict:
    body = _example("job_create.intake_document.json")
    body["deadline_at"] = "2099-01-01T00:00:00Z"
    return body


class FakeKernel:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.materialize_calls = 0
        self.derived_calls = 0
        self.render_calls = 0
        self.last_filename: str | None = None
        self.last_artifact: dict[str, Any] | None = None
        self.last_derived: dict[str, Any] | None = None
        self.last_render: dict[str, Any] | None = None

    def materialize_intake(
        self,
        *,
        document_b64: str,
        document_filename: str,
        media_type: str,
        sha256: str | None = None,
    ) -> dict[str, Any]:
        self.materialize_calls += 1
        assert document_b64
        raw = base64.b64decode(document_b64)
        digest = hashlib.sha256(raw).hexdigest()
        if sha256 is not None:
            assert digest == sha256
        return {
            "schema_version": "prodocux_opaque_artifact_v1",
            "artifact_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "uri": (
                "artifact://intake/"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/"
                f"{document_filename}"
            ),
            "sha256": digest,
            "size_bytes": len(raw),
            "media_type": media_type,
        }

    def extract_content_blocks_from_artifact(
        self, *, document_artifact: dict[str, Any], document_filename: str
    ) -> dict[str, Any]:
        self.calls += 1
        self.last_filename = document_filename
        self.last_artifact = document_artifact
        assert str(document_artifact["uri"]).startswith("artifact://")
        if self.calls <= self.fail_times:
            raise RuntimeError("kernel down")
        return {
            "schema_version": "prodocux_content_blocks_v1",
            "ok": True,
            "blocks": [],
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
        self.last_derived = {
            "schema_version": "prodocux_opaque_artifact_v1",
            "artifact_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "uri": (
                "artifact://derived/"
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/"
                f"{output_name}"
            ),
            "sha256": digest,
            "size_bytes": len(raw),
            "media_type": media_type,
        }
        return dict(self.last_derived)

    def render_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.render_calls += 1
        self.last_render = dict(payload)
        if self.render_calls <= self.fail_times:
            raise RuntimeError("kernel down")
        name = str((payload.get("output") or {}).get("output_name") or "out.bin")
        body = b"rendered"
        digest = hashlib.sha256(body).hexdigest()
        return {
            "status": "completed",
            "artifact": {
                "schema_version": "prodocux_opaque_artifact_v1",
                "artifact_id": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                "uri": f"artifact://sink/{name}",
                "sha256": digest,
                "size_bytes": len(body),
                "media_type": "application/octet-stream",
            },
        }


def _service(tmp_path: Path) -> tuple[JobService, JobStore, StagingStore]:
    store = JobStore(tmp_path / "jobs.sqlite3")
    staging = StagingStore(tmp_path / "staging", ttl_seconds=3600)
    service = JobService(store=store, staging=staging, contract_root=PHASE0)
    return service, store, staging


def test_reconcile_fails_closed_when_staging_missing(tmp_path: Path) -> None:
    service, store, staging = _service(tmp_path)
    body = _live_create_body()
    _, doc = service.create(body)
    staging.delete(doc["staging"]["handle"])
    reconciled = service.reconcile(
        body["job_id"],
        {
            "schema_version": "pdx_internal_job_reconcile_v1",
            "job_id": body["job_id"],
            "request_id": "req-reconcile-1",
            "correlation_id": body["correlation_id"],
        },
    )
    assert reconciled["state"] == "failed"
    assert reconciled["error"]["code"] == "STAGING_MISSING"
    assert "staging" not in reconciled
    assert "content_b64" not in json.dumps(reconciled)


def test_reconcile_releases_expired_lease_to_pending(tmp_path: Path) -> None:
    service, store, staging = _service(tmp_path)
    body = _live_create_body()
    service.create(body)
    claimed = store.claim_next(owner="w1", lease_seconds=1, max_attempts=3)
    assert claimed is not None
    assert claimed.state == "running"
    # Force lease expiry.
    claimed.lease_expires_unix = 1
    store.update(claimed)
    reconciled = service.reconcile(
        body["job_id"],
        {
            "schema_version": "pdx_internal_job_reconcile_v1",
            "job_id": body["job_id"],
            "request_id": "req-reconcile-2",
            "correlation_id": body["correlation_id"],
        },
    )
    assert reconciled["state"] == "pending"
    fresh = store.get(body["job_id"])
    assert fresh is not None
    assert fresh.lease_owner is None


def test_worker_completes_intake_via_kernel(tmp_path: Path) -> None:
    service, store, staging = _service(tmp_path)
    body = _live_create_body()
    _, created = service.create(body)
    handle = created["staging"]["handle"]
    kernel = FakeKernel()
    worker = JobWorker(
        store=store,
        staging=staging,
        service=service,
        kernel=kernel,
        owner="test-worker",
        max_attempts=3,
    )
    finished = worker.run_once()
    assert finished is not None
    assert finished.state == "completed"
    assert kernel.materialize_calls == 1
    assert kernel.calls == 1
    assert kernel.derived_calls == 1
    assert kernel.last_filename == "document.pdf"
    assert kernel.last_artifact is not None
    assert kernel.last_artifact["uri"].startswith("artifact://")
    assert staging.read_bytes(handle) is None
    status = service.get(body["job_id"])
    assert status["state"] == "completed"
    assert "staging" not in status
    assert "content_b64" not in json.dumps(status)
    result = service.get_result(body["job_id"])
    assert result["schema_version"] == "pdx_internal_job_result_v1"
    assert result["kind"] == "materialized_source"
    assert result["job_id"] == body["job_id"]
    assert result["artifact"]["uri"].startswith("artifact://intake/")
    assert (
        result["artifact"]["artifact_id"]
        in result["artifact"]["uri"]
    )
    assert "content_b64" not in json.dumps(result)
    # Status v1 remains free of result fields.
    assert "result" not in status
    assert "artifact" not in status
    results = service.get_results(body["job_id"])
    assert results["schema_version"] == "pdx_internal_job_results_v1"
    assert [item["kind"] for item in results["results"]] == [
        "materialized_source",
        "processing_output",
    ]
    assert results["results"][1]["artifact"]["uri"].startswith("artifact://derived/")


def test_worker_render_artifact_persists_processing_output(tmp_path: Path) -> None:
    service, store, staging = _service(tmp_path)
    render_req = {
        "schema_version": "prodocux_render_request_v1",
        "request_id": "render-job-1",
        "target_format": "csv",
        "content": {
            "schema_version": "prodocux_content_blocks_v1",
            "blocks": [
                {
                    "id": "sheet1",
                    "type": "sheet",
                    "name": "Records",
                    "table": {"header_rows": 1, "rows": [["id"], ["1"]]},
                }
            ],
        },
        "output": {"output_name": "records.csv", "delivery_mode": "artifact"},
    }
    raw = json.dumps(render_req, ensure_ascii=True, separators=(",", ":")).encode(
        "utf-8"
    )
    digest = hashlib.sha256(raw).hexdigest()
    body = {
        "schema_version": "pdx_internal_job_create_v1",
        "job_id": "job-render-1",
        "operation": "render_artifact",
        "subject": {"binding_id": "subject-render-1", "revision": "rev-1"},
        "input_digest": digest,
        "operation_digest": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        "idempotency_key": "job-render-1:render_artifact",
        "correlation_id": "correlation-render-1",
        "request_id": "request-render-1",
        "deadline_at": "2099-01-01T00:00:00Z",
        "kernel_contract": "v1",
        "payload": {
            "encoding": "base64",
            "media_type": "application/json",
            "filename": "render_request.json",
            "content_b64": base64.b64encode(raw).decode("ascii"),
            "decoded_size_bytes": len(raw),
        },
    }
    service.create(body)
    kernel = FakeKernel()
    worker = JobWorker(
        store=store,
        staging=staging,
        service=service,
        kernel=kernel,
        owner="render-worker",
    )
    finished = worker.run_once()
    assert finished is not None
    assert finished.state == "completed"
    assert kernel.render_calls == 1
    result = service.get_result(body["job_id"])
    assert result["kind"] == "processing_output"
    assert result["artifact"]["uri"].startswith("artifact://sink/")
    results = service.get_results(body["job_id"])
    assert len(results["results"]) == 1
    assert results["results"][0]["kind"] == "processing_output"


def test_worker_retries_then_fails(tmp_path: Path) -> None:
    service, store, staging = _service(tmp_path)
    body = _live_create_body()
    service.create(body)
    kernel = FakeKernel(fail_times=99)
    worker = JobWorker(
        store=store,
        staging=staging,
        service=service,
        kernel=kernel,
        owner="test-worker",
        max_attempts=2,
    )
    # First attempt: release to pending.
    first = worker.run_once()
    assert first is not None
    assert first.state == "pending"
    # Second attempt: terminal failed.
    second = worker.run_once()
    assert second is not None
    assert second.state == "failed"
    assert second.document["error"]["code"] == "KERNEL_CALL_FAILED"


def test_http_reconcile_and_cancel_path(tmp_path: Path) -> None:
    from pdx_artifact_engine.internal_http import make_server
    import json as json_mod
    import threading
    import urllib.request

    server = make_server(
        host="127.0.0.1",
        port=0,
        db_path=tmp_path / "jobs.sqlite3",
        staging_root=tmp_path / "staging",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        body = _live_create_body()
        create_req = urllib.request.Request(
            f"http://{host}:{port}/internal/v1/jobs",
            data=json_mod.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(create_req) as resp:
            created = json_mod.loads(resp.read().decode("utf-8"))
        # Delete staging under the server's store by path.
        staging = StagingStore(tmp_path / "staging")
        staging.delete(created["staging"]["handle"])
        recon_body = {
            "schema_version": "pdx_internal_job_reconcile_v1",
            "job_id": body["job_id"],
            "request_id": "req-http-recon",
            "correlation_id": body["correlation_id"],
        }
        recon_req = urllib.request.Request(
            f"http://{host}:{port}/internal/v1/jobs/{body['job_id']}/reconcile",
            data=json_mod.dumps(recon_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(recon_req) as resp:
            assert resp.status == 200
            doc = json_mod.loads(resp.read().decode("utf-8"))
        assert doc["state"] == "failed"
        assert doc["error"]["code"] == "STAGING_MISSING"
    finally:
        server.shutdown()
        server.server_close()