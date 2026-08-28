"""Audit follow-up: packaged schemas, atomic claim, verified retrieve, safe JSON."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdx_artifact_engine.jobs import JobRecord, JobStore
from pdx_artifact_engine.jobs.service import JobService, JobServiceError
from pdx_artifact_engine.staging import StagingStore


def test_job_service_loads_packaged_schemas(tmp_path: Path) -> None:
    service = JobService(
        store=JobStore(tmp_path / "jobs.sqlite3"),
        staging=StagingStore(tmp_path / "staging"),
    )
    with pytest.raises(JobServiceError) as excinfo:
        service.create(["not-an-object"])  # type: ignore[arg-type]
    assert excinfo.value.code == "REQUEST_INVALID"
    assert excinfo.value.status == 400


def test_claim_next_is_atomic_across_connections(tmp_path: Path) -> None:
    db = tmp_path / "jobs.sqlite3"
    first = JobStore(db)
    first.insert(
        JobRecord(
            job_id="job-claim-1",
            state="pending",
            document={
                "schema_version": "pdx_internal_job_status_v1",
                "job_id": "job-claim-1",
                "operation": "render_artifact",
                "state": "pending",
                "input_digest": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                "operation_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "idempotency_key": "job-claim-1:render_artifact",
                "correlation_id": "c",
                "request_id": "r",
                "kernel_contract": "v1",
            },
            idempotency_key="job-claim-1:render_artifact",
            operation_digest="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
    )
    second = JobStore(db)
    claimed = first.claim_next(owner="w1", lease_seconds=60)
    raced = second.claim_next(owner="w2", lease_seconds=60)
    assert claimed is not None
    assert claimed.lease_owner == "w1"
    assert raced is None
