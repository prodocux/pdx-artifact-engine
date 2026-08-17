from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pdx_artifact_core import (
    ApprovalError,
    ApprovalLedger,
    build_resumed_plan,
    cancel_checkpoint,
    create_approval_request,
    create_checkpoint,
)


def _plan() -> dict:
    return {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "approval-test",
        "producer": {"type": "manual"},
        "steps": [
            {"id": "already_written", "kind": "tool", "tool": "side.effect"},
            {
                "id": "after_approval",
                "kind": "tool",
                "tool": "finish",
                "depends_on": ["already_written"],
            },
        ],
    }


def _decision(checkpoint, request, **changes):
    value = {
        "decision_id": str(uuid.uuid4()),
        "approval_request_id": request["approval_request_id"],
        "checkpoint_id": checkpoint["checkpoint_id"],
        "idempotency_key": "resume-once",
        "actor_id": "human-1",
        "decision": "approved",
        "subject_digest": checkpoint["subject_digest"],
        "plan_digest": checkpoint["plan_digest"],
        "evidence_digests": checkpoint["evidence_digests"],
        "decided_at": datetime.now(UTC).isoformat(),
    }
    value.update(changes)
    return value


def test_resume_plan_never_contains_completed_side_effect_step() -> None:
    plan = _plan()
    checkpoint = create_checkpoint(
        plan=plan,
        run_id="run-1",
        subject_digest="a" * 64,
        completed_step_ids=["already_written"],
        pending_step_ids=["after_approval"],
        evidence_digests={},
    )
    request = create_approval_request(checkpoint)
    decision = _decision(checkpoint, request)
    ApprovalLedger().record(checkpoint, request, decision)
    resumed = build_resumed_plan(plan, checkpoint, decision)
    assert [step["id"] for step in resumed["steps"]] == ["after_approval"]
    assert resumed["steps"][0]["depends_on"] == []


def test_identical_replay_is_idempotent_but_changed_replay_fails() -> None:
    plan = _plan()
    checkpoint = create_checkpoint(
        plan=plan,
        run_id="run-1",
        subject_digest="a" * 64,
        completed_step_ids=["already_written"],
        pending_step_ids=["after_approval"],
        evidence_digests={},
    )
    request = create_approval_request(checkpoint)
    decision = _decision(checkpoint, request)
    ledger = ApprovalLedger()
    assert ledger.record(checkpoint, request, decision) == ledger.record(
        checkpoint, request, decision
    )
    with pytest.raises(ApprovalError, match="reused"):
        ledger.record(checkpoint, request, {**decision, "decision": "rejected"})


def test_double_decision_and_digest_mismatch_fail_closed() -> None:
    plan = _plan()
    checkpoint = create_checkpoint(
        plan=plan,
        run_id="run-1",
        subject_digest="a" * 64,
        completed_step_ids=["already_written"],
        pending_step_ids=["after_approval"],
        evidence_digests={},
    )
    request = create_approval_request(checkpoint)
    decision = _decision(checkpoint, request)
    ledger = ApprovalLedger()
    ledger.record(checkpoint, request, decision)
    with pytest.raises(ApprovalError, match="already decided"):
        ledger.record(
            checkpoint,
            request,
            _decision(checkpoint, request, idempotency_key="another"),
        )
    with pytest.raises(ApprovalError, match="plan digest"):
        build_resumed_plan({**plan, "request_id": "changed"}, checkpoint, decision)


def test_reject_and_cancel_do_not_resume() -> None:
    plan = _plan()
    checkpoint = create_checkpoint(
        plan=plan,
        run_id="run-1",
        subject_digest="a" * 64,
        completed_step_ids=["already_written"],
        pending_step_ids=["after_approval"],
        evidence_digests={},
    )
    request = create_approval_request(checkpoint)
    rejected = _decision(checkpoint, request, decision="rejected")
    ApprovalLedger().record(checkpoint, request, rejected)
    with pytest.raises(ApprovalError, match="approved"):
        build_resumed_plan(plan, checkpoint, rejected)
    assert cancel_checkpoint(checkpoint)["status"] == "cancelled"
