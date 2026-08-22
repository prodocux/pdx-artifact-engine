from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pdx_artifact_core import (
    InMemoryCheckpointRepository,
    InMemoryDecisionRepository,
    SnapshotError,
    create_approval_request,
    create_checkpoint,
    create_run_snapshot,
    decode_run_snapshot,
    encode_run_snapshot,
    snapshot_digest,
)
from pdx_artifact_engine import ArtifactRuntime
from pdx_artifact_engine.registry import SkillDefinition, SkillRegistry


def _plan() -> dict:
    return {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "snapshot-resume-test",
        "producer": {"type": "manual"},
        "steps": [
            {
                "id": "fetch",
                "kind": "tool",
                "tool": "side.effect.fetch",
                "outputs": ["result"],
            },
            {
                "id": "finish",
                "kind": "tool",
                "tool": "finish",
                "depends_on": ["fetch"],
                "inputs": {"payload": "$fetch.result"},
            },
        ],
    }


def _identity() -> dict:
    return {
        "artifact_id": "fetch-result",
        "uri": "artifact://snapshot-resume/fetch/result.json",
        "sha256": "dc60e632a90329ccfd34fbe904d94704dbbb6669575185e26389854ff64139c3",
        "size_bytes": 12,
        "media_type": "application/json",
        "created_at": "2026-08-22T00:00:00Z",
    }


def _receipt() -> dict:
    identity = _identity()
    return {
        "schema_version": "pdx_step_receipt_v1",
        "receipt_id": "receipt-fetch-1",
        "run_id": "run-snapshot-resume",
        "step_id": "fetch",
        "status": "completed",
        "attempt": 1,
        "request_digest": "a" * 64,
        "input_digest": "b" * 64,
        "output_digest": "c" * 64,
        "artifacts": [identity],
        "output_bindings": [{"name": "result", "artifact": identity}],
        "recorded_at": "2026-08-22T00:00:00Z",
    }


def _checkpoint(plan: dict) -> dict:
    return create_checkpoint(
        plan=plan,
        run_id="run-snapshot-resume",
        subject_digest="d" * 64,
        completed_step_ids=["fetch"],
        pending_step_ids=["finish"],
        evidence_digests={},
        checkpoint_id="checkpoint-snapshot-resume",
    )


def _decision(checkpoint: dict) -> dict:
    request = create_approval_request(checkpoint)
    return {
        "decision_id": str(uuid.uuid4()),
        "approval_request_id": request["approval_request_id"],
        "checkpoint_id": checkpoint["checkpoint_id"],
        "idempotency_key": "snapshot-resume-once",
        "actor_id": "human-1",
        "decision": "approved",
        "subject_digest": checkpoint["subject_digest"],
        "plan_digest": checkpoint["plan_digest"],
        "evidence_digests": checkpoint["evidence_digests"],
        "decided_at": datetime.now(UTC).isoformat(),
    }


def _snapshot() -> tuple[dict, dict, dict]:
    plan = _plan()
    checkpoint = _checkpoint(plan)
    snapshot = create_run_snapshot(
        checkpoint=checkpoint,
        step_receipts=[_receipt()],
        state="awaiting_approval",
        snapshot_id="snapshot-resume",
        created_at="2026-08-22T00:00:00Z",
    )
    return plan, checkpoint, snapshot


def test_snapshot_codec_rejects_tampering() -> None:
    _, _, snapshot = _snapshot()
    encoded = encode_run_snapshot(snapshot)
    assert decode_run_snapshot(encoded) == snapshot
    tampered = encoded.replace(b'"event_sequence":0', b'"event_sequence":1')
    with pytest.raises(SnapshotError, match="digest mismatch"):
        decode_run_snapshot(tampered)


def test_checkpoint_repository_is_isolated_and_compare_and_set() -> None:
    _, _, snapshot = _snapshot()
    repository = InMemoryCheckpointRepository()
    assert repository.put_if_absent(snapshot)
    assert not repository.put_if_absent(snapshot)
    loaded = repository.get(snapshot["snapshot_id"])
    assert loaded == snapshot
    loaded["state"] = "failed"
    assert repository.get(snapshot["snapshot_id"]) == snapshot

    next_snapshot = deepcopy(snapshot)
    next_snapshot["snapshot_version"] = 2
    next_snapshot["event_sequence"] = 1
    next_snapshot["snapshot_digest"] = snapshot_digest(next_snapshot)
    assert not repository.compare_and_set(snapshot["snapshot_id"], 0, next_snapshot)
    assert repository.compare_and_set(snapshot["snapshot_id"], 1, next_snapshot)


def test_decision_repository_is_idempotent_and_conflict_safe() -> None:
    plan = _plan()
    checkpoint = _checkpoint(plan)
    decision = _decision(checkpoint)
    repository = InMemoryDecisionRepository()
    assert repository.record_once(decision) == decision
    assert repository.record_once(decision) == decision
    assert repository.get_by_checkpoint_id(checkpoint["checkpoint_id"]) == decision
    with pytest.raises(SnapshotError, match="identity conflict"):
        repository.record_once({**decision, "decision": "rejected"})


class MemoryStorage:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def exists(self, uri: str) -> bool:
        return uri in self.values

    def resolve(self, uri: str) -> object:
        return deepcopy(self.values[uri])


def test_cross_process_resume_materializes_outputs_without_rerunning_side_effect(
    tmp_path: Path,
) -> None:
    plan, checkpoint, snapshot = _snapshot()
    persisted = decode_run_snapshot(encode_run_snapshot(snapshot))
    observed: list[dict] = []

    def finish(inputs: dict, output_dir: Path) -> dict:
        observed.append(inputs)
        return {"outputs": {"done": True}}

    registry = SkillRegistry(
        [
            SkillDefinition(
                name="finish",
                version="1",
                domain="test",
                description="finish from a durable prior output",
                entrypoint="test",
                inputs=("payload",),
                outputs=("done",),
                artifacts=(),
                failure_codes=({"code": "FAIL", "meaning": "test"},),
                verification_hooks=(),
            )
        ]
    )
    runtime = ArtifactRuntime(
        registry,
        executors={"finish": finish},
        storage=MemoryStorage({_identity()["uri"]: {"value": 42}}),
    )
    result = runtime.resume_snapshot(
        plan, persisted, _decision(checkpoint), tmp_path
    )

    assert result["run_manifest"]["status"] == "completed"
    assert observed == [{"payload": {"value": 42}}]


def test_resume_rejects_terminal_snapshot_and_artifact_drift(tmp_path: Path) -> None:
    plan, checkpoint, snapshot = _snapshot()
    terminal = deepcopy(snapshot)
    terminal["state"] = "completed"
    terminal["snapshot_digest"] = snapshot_digest(terminal)
    runtime = ArtifactRuntime(SkillRegistry([]))
    with pytest.raises(SnapshotError, match="awaiting_approval"):
        runtime.resume_snapshot(plan, terminal, _decision(checkpoint), tmp_path)

    runtime = ArtifactRuntime(
        SkillRegistry([]),
        storage=MemoryStorage({_identity()["uri"]: {"value": 41}}),
    )
    with pytest.raises(SnapshotError, match="digest mismatch"):
        runtime.resume_snapshot(plan, snapshot, _decision(checkpoint), tmp_path)


def test_resume_rejects_missing_checkpoint_and_ambiguous_side_effect(
    tmp_path: Path,
) -> None:
    plan = _plan()
    missing = _snapshot()[2]
    del missing["checkpoint"]
    with pytest.raises(SnapshotError, match="invalid run snapshot"):
        ArtifactRuntime(SkillRegistry([])).resume_snapshot(
            plan, missing, {}, tmp_path
        )

    checkpoint = create_checkpoint(
        plan=plan,
        run_id="run-snapshot-resume",
        subject_digest="d" * 64,
        completed_step_ids=[],
        pending_step_ids=["fetch", "finish"],
        evidence_digests={},
        checkpoint_id="checkpoint-ambiguous",
    )
    receipt = _receipt()
    receipt.pop("output_digest")
    receipt.pop("artifacts")
    receipt.pop("output_bindings")
    receipt["status"] = "unknown_outcome"
    receipt["error"] = {
        "code": "OUTCOME_UNKNOWN",
        "message": "The host must reconcile before retry.",
        "retryable": False,
        "reconcile_required": True,
    }
    snapshot = create_run_snapshot(
        checkpoint=checkpoint,
        step_receipts=[receipt],
        state="awaiting_approval",
        snapshot_id="snapshot-ambiguous",
        created_at="2026-08-22T00:00:00Z",
    )
    with pytest.raises(SnapshotError, match="reconciliation is required"):
        ArtifactRuntime(SkillRegistry([])).resume_snapshot(
            plan, snapshot, _decision(checkpoint), tmp_path
        )
