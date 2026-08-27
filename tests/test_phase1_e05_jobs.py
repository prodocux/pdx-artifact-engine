"""Phase 1 E-05 private job create/get/cancel against Phase 0 fixtures."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from pathlib import Path

import pytest

from pdx_artifact_engine.internal_http import make_server
from pdx_artifact_engine.jobs import JobStore
from pdx_artifact_engine.jobs.service import JobService, JobServiceError
from pdx_artifact_engine.staging import StagingStore

ROOT = Path(__file__).resolve().parents[1]
PHASE0 = ROOT / "docs" / "phase0"


def _example(name: str) -> dict:
    return json.loads((PHASE0 / "examples" / name).read_text(encoding="utf-8"))


def test_create_get_omits_payload_bytes(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    staging = StagingStore(tmp_path / "staging", ttl_seconds=3600)
    service = JobService(store=store, staging=staging, contract_root=PHASE0)
    body = _example("job_create.intake_document.json")
    status, doc = service.create(body)
    assert status == 202
    assert doc["state"] == "pending"
    assert "content_b64" not in json.dumps(doc)
    assert doc["staging"]["handle"].startswith("stg_")
    assert staging.read_bytes(doc["staging"]["handle"]) == base64.b64decode(
        body["payload"]["content_b64"]
    )
    got = service.get(body["job_id"])
    assert got["job_id"] == body["job_id"]
    assert "queued" not in json.dumps(got)


def test_idempotency_conflict(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    staging = StagingStore(tmp_path / "staging")
    service = JobService(store=store, staging=staging, contract_root=PHASE0)
    first = _example("job_create.intake_document.json")
    second = _example("job_create.idempotency_conflict.json")
    service.create(first)
    with pytest.raises(JobServiceError) as excinfo:
        service.create(second)
    assert excinfo.value.status == 409
    assert excinfo.value.code == "IDEMPOTENCY_CONFLICT"


def test_cancel_deletes_staging(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    staging = StagingStore(tmp_path / "staging")
    service = JobService(store=store, staging=staging, contract_root=PHASE0)
    body = _example("job_create.intake_document.json")
    _, doc = service.create(body)
    handle = doc["staging"]["handle"]
    cancelled = service.cancel(
        body["job_id"],
        {
            "schema_version": "pdx_internal_job_cancel_v1",
            "job_id": body["job_id"],
            "request_id": body["request_id"],
            "correlation_id": body["correlation_id"],
        },
    )
    assert cancelled["state"] == "cancelled"
    assert "staging" not in cancelled
    assert staging.read_bytes(handle) is None


def test_http_create_and_get(tmp_path: Path) -> None:
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
        import urllib.request

        body = _example("job_create.intake_document.json")
        raw = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"http://{host}:{port}/internal/v1/jobs",
            data=raw,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 202
            created = json.loads(resp.read().decode("utf-8"))
        assert created["state"] == "pending"
        assert "content_b64" not in json.dumps(created)

        get_req = urllib.request.Request(
            f"http://{host}:{port}/internal/v1/jobs/{body['job_id']}"
        )
        with urllib.request.urlopen(get_req) as resp:
            assert resp.status == 200
            got = json.loads(resp.read().decode("utf-8"))
        assert got["job_id"] == body["job_id"]
        assert hashlib.sha256(
            base64.b64decode(body["payload"]["content_b64"])
        ).hexdigest() == got["input_digest"]
    finally:
        server.shutdown()
        server.server_close()
