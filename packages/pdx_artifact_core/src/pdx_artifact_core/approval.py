"""Product-neutral approval checkpoint and replay-safe resume primitives."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any


class ApprovalError(ValueError):
    """Approval contract or state transition failed closed."""


def canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def create_checkpoint(
    *,
    plan: Mapping[str, Any],
    run_id: str,
    subject_digest: str,
    completed_step_ids: list[str],
    pending_step_ids: list[str],
    evidence_digests: Mapping[str, str],
    checkpoint_id: str | None = None,
) -> dict[str, Any]:
    step_ids = [str(step["id"]) for step in plan.get("steps", [])]
    completed, pending = set(completed_step_ids), set(pending_step_ids)
    if completed & pending or not completed | pending <= set(step_ids):
        raise ApprovalError("checkpoint step partition is invalid")
    if completed | pending != set(step_ids):
        raise ApprovalError("checkpoint must account for every plan step")
    return {
        "checkpoint_id": checkpoint_id or f"chk_{uuid.uuid4().hex}",
        "run_id": run_id,
        "subject_digest": subject_digest,
        "plan_digest": canonical_digest(plan),
        "completed_step_ids": [item for item in step_ids if item in completed],
        "pending_step_ids": [item for item in step_ids if item in pending],
        "evidence_digests": dict(evidence_digests),
        "status": "pending",
        "created_at": datetime.now(UTC).isoformat(),
    }


def create_approval_request(
    checkpoint: Mapping[str, Any], *, summary: str = ""
) -> dict[str, Any]:
    if checkpoint.get("status") != "pending":
        raise ApprovalError("approval request requires a pending checkpoint")
    return {
        "approval_request_id": str(uuid.uuid4()),
        "run_id": checkpoint["run_id"],
        "checkpoint_id": checkpoint["checkpoint_id"],
        "subject_digest": checkpoint["subject_digest"],
        "plan_digest": checkpoint["plan_digest"],
        "evidence_digests": dict(checkpoint["evidence_digests"]),
        "summary": summary,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "pending",
    }


class ApprovalLedger:
    """Small in-memory reference ledger; hosts may persist the same contract."""

    def __init__(self) -> None:
        self._by_key: dict[str, dict[str, Any]] = {}
        self._by_checkpoint: dict[str, dict[str, Any]] = {}

    def record(
        self,
        checkpoint: Mapping[str, Any],
        request: Mapping[str, Any],
        decision: Mapping[str, Any],
    ) -> dict[str, Any]:
        key = str(decision.get("idempotency_key", ""))
        if not key:
            raise ApprovalError("idempotency_key is required")
        existing = self._by_key.get(key)
        normalized = dict(decision)
        if existing is not None:
            if existing == normalized:
                return deepcopy(existing)
            raise ApprovalError("idempotency key was reused with different content")
        if (
            checkpoint.get("status") != "pending"
            or checkpoint["checkpoint_id"] in self._by_checkpoint
        ):
            raise ApprovalError("checkpoint was already decided")
        pairs = (
            ("checkpoint_id", checkpoint["checkpoint_id"]),
            ("approval_request_id", request["approval_request_id"]),
            ("subject_digest", checkpoint["subject_digest"]),
            ("plan_digest", checkpoint["plan_digest"]),
            ("evidence_digests", checkpoint["evidence_digests"]),
        )
        for field, expected in pairs:
            if normalized.get(field) != expected:
                raise ApprovalError(f"approval decision {field} mismatch")
        if normalized.get("decision") not in {"approved", "rejected"}:
            raise ApprovalError("decision must be approved or rejected")
        self._by_key[key] = deepcopy(normalized)
        self._by_checkpoint[str(checkpoint["checkpoint_id"])] = deepcopy(normalized)
        return deepcopy(normalized)


def build_resumed_plan(
    plan: Mapping[str, Any], checkpoint: Mapping[str, Any], decision: Mapping[str, Any]
) -> dict[str, Any]:
    if decision.get("decision") != "approved":
        raise ApprovalError("only an approved decision may resume execution")
    if canonical_digest(plan) != checkpoint.get("plan_digest"):
        raise ApprovalError("plan digest changed after checkpoint")
    for field in ("checkpoint_id", "subject_digest", "plan_digest", "evidence_digests"):
        if decision.get(field) != checkpoint.get(field):
            raise ApprovalError(f"resume {field} mismatch")
    pending = set(checkpoint.get("pending_step_ids", []))
    resumed = deepcopy(dict(plan))
    resumed["steps"] = [
        step for step in resumed.get("steps", []) if step["id"] in pending
    ]
    for step in resumed["steps"]:
        step["depends_on"] = [
            dep for dep in step.get("depends_on", []) if dep in pending
        ]
    return resumed


def cancel_checkpoint(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    if checkpoint.get("status") != "pending":
        raise ApprovalError("only a pending checkpoint may be cancelled")
    result = dict(checkpoint)
    result["status"] = "cancelled"
    return result
