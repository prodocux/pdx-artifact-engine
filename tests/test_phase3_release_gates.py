"""Audit follow-up: packaged schemas, atomic claim, verified retrieve, safe JSON."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pdx_artifact_engine.jobs import JobRecord, JobStore
from pdx_artifact_engine.jobs.service import JobService, JobServiceError
from pdx_artifact_engine.staging import StagingStore

ROOT = Path(__file__).resolve().parents[1]
PHASE0 = ROOT / "docs" / "phase0"


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
    assert claimed.lease_token
    assert raced is None


def test_stale_owner_cannot_renew_or_finalize_reclaimed_job(tmp_path: Path) -> None:
    """Same hostname/owner must not keep a lease after another attempt claimed it."""
    db = tmp_path / "jobs.sqlite3"
    store = JobStore(db)
    staging = StagingStore(tmp_path / "staging")
    service = JobService(store=store, staging=staging)
    store.insert(
        JobRecord(
            job_id="job-lease-1",
            state="pending",
            document={
                "schema_version": "pdx_internal_job_status_v1",
                "job_id": "job-lease-1",
                "operation": "render_artifact",
                "state": "pending",
                "input_digest": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                "operation_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "idempotency_key": "job-lease-1:render_artifact",
                "correlation_id": "c",
                "request_id": "r",
                "kernel_contract": "v1",
            },
            idempotency_key="job-lease-1:render_artifact",
            operation_digest="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
    )
    first = store.claim_next(owner="shared-host", lease_seconds=1, now=100)
    assert first is not None
    stale_token = first.lease_token
    assert stale_token
    assert first.attempt_count == 1

    first.lease_expires_unix = 100
    assert store.update(first) is True

    reclaimed = store.claim_next(owner="shared-host", lease_seconds=60, now=200)
    assert reclaimed is not None
    assert reclaimed.attempt_count == 2
    assert reclaimed.lease_token
    assert reclaimed.lease_token != stale_token

    stale_renew = store.renew_lease(
        first.job_id,
        owner="shared-host",
        lease_token=stale_token,
        lease_seconds=60,
        now=200,
    )
    assert stale_renew is False

    applied = service._finalize(
        first,
        state="completed",
        error=None,
        expected_lease_token=stale_token,
    )
    assert applied is None
    fresh = store.get(first.job_id)
    assert fresh is not None
    assert fresh.state == "running"
    assert fresh.attempt_count == 2
    assert fresh.lease_token == reclaimed.lease_token
    assert store.renew_lease(
        first.job_id,
        owner="shared-host",
        lease_token=reclaimed.lease_token,
        lease_seconds=60,
        now=200,
    )
    assert store.holds_lease(
        first.job_id, owner="shared-host", lease_token=reclaimed.lease_token
    )
    assert not store.holds_lease(
        first.job_id, owner="shared-host", lease_token=stale_token
    )


def test_default_worker_instance_ids_are_unique() -> None:
    from pdx_artifact_engine.worker import default_worker_instance_id

    first = default_worker_instance_id()
    second = default_worker_instance_id()
    assert first != second
    assert first
    assert second


def _pending_record(job_id: str) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        state="pending",
        document={
            "schema_version": "pdx_internal_job_status_v1",
            "job_id": job_id,
            "operation": "render_artifact",
            "state": "pending",
            "input_digest": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
            "operation_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "idempotency_key": f"{job_id}:render_artifact",
            "correlation_id": "c",
            "request_id": "r",
            "kernel_contract": "v1",
        },
        idempotency_key=f"{job_id}:render_artifact",
        operation_digest="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )


def test_release_expired_lease_cas_loses_to_reclaim_on_other_connection(
    tmp_path: Path,
) -> None:
    db = tmp_path / "jobs.sqlite3"
    first_store = JobStore(db)
    first_store.insert(_pending_record("job-lease-race-1"))
    claimed = first_store.claim_next(owner="w-a", lease_seconds=1, now=100)
    assert claimed is not None
    stale_token = claimed.lease_token
    assert stale_token
    claimed.lease_expires_unix = 100
    assert first_store.update(claimed) is True

    second_store = JobStore(db)
    reclaimed = second_store.claim_next(owner="w-b", lease_seconds=60, now=200)
    assert reclaimed is not None
    assert reclaimed.lease_token != stale_token

    stale_update = first_store.release_expired_lease(
        claimed.job_id, lease_token=stale_token, now=200
    )
    assert stale_update is False
    fresh = first_store.get(claimed.job_id)
    assert fresh is not None
    assert fresh.state == "running"
    assert fresh.lease_token == reclaimed.lease_token
    assert fresh.lease_owner == "w-b"


def test_release_expired_lease_refuses_live_lease(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.insert(_pending_record("job-lease-live-1"))
    claimed = store.claim_next(owner="w1", lease_seconds=60, now=100)
    assert claimed is not None
    assert claimed.lease_token
    assert (
        store.release_expired_lease(
            claimed.job_id, lease_token=claimed.lease_token, now=100
        )
        is False
    )
    fresh = store.get(claimed.job_id)
    assert fresh is not None
    assert fresh.state == "running"
    assert fresh.lease_token == claimed.lease_token


def test_reconcile_does_not_clobber_reclaimed_lease(tmp_path: Path) -> None:
    """Reconcile snapshot of attempt A must not wipe worker B's new claim."""
    db = tmp_path / "jobs.sqlite3"
    store = JobStore(db)
    staging = StagingStore(tmp_path / "staging", ttl_seconds=3600)
    service = JobService(store=store, staging=staging, contract_root=PHASE0)
    body = json.loads(
        (PHASE0 / "examples" / "job_create.intake_document.json").read_text(
            encoding="utf-8"
        )
    )
    body["job_id"] = "job-reconcile-race-1"
    body["idempotency_key"] = "job-reconcile-race-1:intake_document"
    body["deadline_at"] = "2099-01-01T00:00:00Z"
    service.create(body)
    claimed = store.claim_next(owner="w-a", lease_seconds=1, max_attempts=3)
    assert claimed is not None
    stale_token = claimed.lease_token
    claimed.lease_expires_unix = 1
    assert store.update(claimed) is True

    raced: dict[str, JobRecord | None] = {"reclaimed": None}
    inner_get = store.get

    def get_then_reclaim(job_id: str) -> JobRecord | None:
        record = inner_get(job_id)
        if raced["reclaimed"] is None and record is not None and record.state == "running":
            other = JobStore(db)
            raced["reclaimed"] = other.claim_next(
                owner="w-b", lease_seconds=60, max_attempts=3
            )
            other.close()
        return record

    store.get = get_then_reclaim  # type: ignore[method-assign]
    reconciled = service.reconcile(
        body["job_id"],
        {
            "schema_version": "pdx_internal_job_reconcile_v1",
            "job_id": body["job_id"],
            "request_id": "req-reconcile-race",
            "correlation_id": body["correlation_id"],
        },
    )
    reclaimed = raced["reclaimed"]
    assert reclaimed is not None
    assert reclaimed.lease_token != stale_token
    assert reconciled["state"] == "running"
    fresh = inner_get(body["job_id"])
    assert fresh is not None
    assert fresh.state == "running"
    assert fresh.lease_token == reclaimed.lease_token
    assert fresh.lease_owner == "w-b"
