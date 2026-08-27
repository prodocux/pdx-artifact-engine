"""P1 dock review fixes: cancel/reconcile schema + HTTP body ceiling."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from pdx_artifact_engine.internal_http import (
    BodyLimitError,
    InternalJobHandler,
    make_server,
    max_request_body_bytes,
)
from pdx_artifact_engine.jobs import JobStore
from pdx_artifact_engine.jobs.service import JobService, JobServiceError
from pdx_artifact_engine.staging import StagingStore

ROOT = Path(__file__).resolve().parents[1]
PHASE0 = ROOT / "docs" / "phase0"


def _live_create_body() -> dict:
    body = json.loads(
        (PHASE0 / "examples" / "job_create.intake_document.json").read_text(
            encoding="utf-8"
        )
    )
    body["deadline_at"] = "2099-01-01T00:00:00Z"
    return body


def _service(tmp_path: Path) -> JobService:
    store = JobStore(tmp_path / "jobs.sqlite3")
    staging = StagingStore(tmp_path / "staging")
    return JobService(store=store, staging=staging, contract_root=PHASE0)


def test_cancel_rejects_invalid_schema_and_job_id_mismatch(tmp_path: Path) -> None:
    service = _service(tmp_path)
    body = _live_create_body()
    service.create(body)

    with pytest.raises(JobServiceError) as missing:
        service.cancel(body["job_id"], {"job_id": body["job_id"]})
    assert missing.value.status == 400
    assert missing.value.code == "REQUEST_INVALID"

    with pytest.raises(JobServiceError) as mismatch:
        service.cancel(
            body["job_id"],
            {
                "schema_version": "pdx_internal_job_cancel_v1",
                "job_id": "other-job",
                "request_id": "req-cancel-bad",
                "correlation_id": body["correlation_id"],
            },
        )
    assert mismatch.value.status == 400
    assert mismatch.value.code == "JOB_ID_MISMATCH"

    with pytest.raises(JobServiceError) as reason:
        service.cancel(
            body["job_id"],
            {
                "schema_version": "pdx_internal_job_cancel_v1",
                "job_id": body["job_id"],
                "request_id": "req-cancel-bad-reason",
                "correlation_id": body["correlation_id"],
                "reason_code": "not-upper",
            },
        )
    assert reason.value.status == 400
    assert reason.value.code == "REQUEST_INVALID"

    with pytest.raises(JobServiceError) as extra:
        service.cancel(
            body["job_id"],
            {
                "schema_version": "pdx_internal_job_cancel_v1",
                "job_id": body["job_id"],
                "request_id": "req-cancel-extra",
                "correlation_id": body["correlation_id"],
                "extra": True,
            },
        )
    assert extra.value.status == 400


def test_reconcile_rejects_invalid_schema_and_job_id_mismatch(tmp_path: Path) -> None:
    service = _service(tmp_path)
    body = _live_create_body()
    service.create(body)

    with pytest.raises(JobServiceError) as bad_version:
        service.reconcile(
            body["job_id"],
            {
                "schema_version": "wrong",
                "job_id": body["job_id"],
                "request_id": "req-recon-1",
                "correlation_id": body["correlation_id"],
            },
        )
    assert bad_version.value.code == "REQUEST_INVALID"

    with pytest.raises(JobServiceError) as mismatch:
        service.reconcile(
            body["job_id"],
            {
                "schema_version": "pdx_internal_job_reconcile_v1",
                "job_id": "other-job",
                "request_id": "req-recon-2",
                "correlation_id": body["correlation_id"],
            },
        )
    assert mismatch.value.code == "JOB_ID_MISMATCH"


def test_max_request_body_bytes_includes_json_margin() -> None:
    assert max_request_body_bytes() == 44_739_244 + 65_536


def test_read_json_enforces_content_length_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = InternalJobHandler.__new__(InternalJobHandler)
    monkeypatch.setattr(
        "pdx_artifact_engine.internal_http.max_request_body_bytes",
        lambda: 100,
    )

    class _Headers(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    handler.headers = _Headers({"Content-Length": "101"})

    class _RFile:
        def read(self, n: int) -> bytes:
            raise AssertionError("must not read oversized body")

    handler.rfile = _RFile()
    with pytest.raises(BodyLimitError) as oversized:
        handler._read_json()
    assert oversized.value.status == 413
    assert oversized.value.code == "BODY_TOO_LARGE"

    handler.headers = _Headers({})
    with pytest.raises(BodyLimitError) as missing:
        handler._read_json()
    assert missing.value.status == 411

    handler.headers = _Headers({"Content-Length": "-1"})
    with pytest.raises(BodyLimitError) as negative:
        handler._read_json()
    assert negative.value.status == 400


def test_http_cancel_schema_rejection(tmp_path: Path) -> None:
    import urllib.error
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
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(create_req) as resp:
            assert resp.status == 202

        bad = {
            "schema_version": "pdx_internal_job_cancel_v1",
            "job_id": "not-the-path-id",
            "request_id": "req-http-cancel",
            "correlation_id": body["correlation_id"],
        }
        cancel_req = urllib.request.Request(
            f"http://{host}:{port}/internal/v1/jobs/{body['job_id']}/cancel",
            data=json.dumps(bad).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(cancel_req)
        assert excinfo.value.code == 400
        payload = json.loads(excinfo.value.read().decode("utf-8"))
        assert payload["code"] == "JOB_ID_MISMATCH"
    finally:
        server.shutdown()
        server.server_close()
