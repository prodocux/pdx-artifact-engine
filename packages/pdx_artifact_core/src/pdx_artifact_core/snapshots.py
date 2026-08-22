"""Bounded snapshot codecs and reference in-memory repositories."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from pdx_artifact_core.validate import load_schema

MAX_SNAPSHOT_BYTES = 2_000_000
_SUCCESS = {"completed", "completed_with_review"}


class SnapshotError(ValueError):
    """A snapshot or durable decision failed closed."""


@lru_cache(maxsize=8)
def _validator(schema_name: str) -> Draft202012Validator:
    names = (
        "artifact_storage_identity.v1.schema.json",
        "workflow_checkpoint.v1.schema.json",
        "step_receipt.v1.schema.json",
        "run_snapshot.v1.schema.json",
        "approval_decision.v1.schema.json",
    )
    registry = Registry()
    for name in names:
        schema = load_schema(name)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(
        load_schema(schema_name),
        registry=registry,
        format_checker=FormatChecker(),
    )


def _schema_errors(schema_name: str, value: Any) -> list[str]:
    validator = _validator(schema_name)
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
        f"{error.message}"
        for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    ]


def snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    """Return SHA-256 over canonical JSON excluding ``snapshot_digest``."""
    content = {key: value for key, value in snapshot.items() if key != "snapshot_digest"}
    encoded = json.dumps(
        content, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_step_receipt(receipt: Mapping[str, Any]) -> list[str]:
    """Validate a step receipt, including unique output binding names."""
    errors = _schema_errors("step_receipt.v1.schema.json", receipt)
    if errors:
        return errors
    names = [binding["name"] for binding in receipt.get("output_bindings", [])]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    errors.extend(f"output_bindings: duplicate name {name!r}" for name in duplicates)
    return errors


def validate_run_snapshot(snapshot: Mapping[str, Any]) -> list[str]:
    """Validate schema, checkpoint/receipt coherence, and canonical digest."""
    errors = _schema_errors("run_snapshot.v1.schema.json", snapshot)
    if errors:
        return errors

    checkpoint = snapshot["checkpoint"]
    if checkpoint["run_id"] != snapshot["run_id"]:
        errors.append("checkpoint/run_id: does not match snapshot run_id")

    receipt_ids: set[str] = set()
    step_ids: set[str] = set()
    successful_steps: set[str] = set()
    for index, receipt in enumerate(snapshot["step_receipts"]):
        receipt_errors = validate_step_receipt(receipt)
        errors.extend(f"step_receipts/{index}/{error}" for error in receipt_errors)
        if receipt["receipt_id"] in receipt_ids:
            errors.append(f"step_receipts/{index}: duplicate receipt_id")
        receipt_ids.add(receipt["receipt_id"])
        if receipt["step_id"] in step_ids:
            errors.append(f"step_receipts/{index}: duplicate step_id")
        step_ids.add(receipt["step_id"])
        if receipt["run_id"] != snapshot["run_id"]:
            errors.append(f"step_receipts/{index}/run_id: does not match snapshot")
        if receipt["status"] in _SUCCESS:
            successful_steps.add(receipt["step_id"])

    completed = set(checkpoint["completed_step_ids"])
    pending = set(checkpoint["pending_step_ids"])
    if completed & pending:
        errors.append("checkpoint: completed and pending step ids must be disjoint")
    unknown_receipts = step_ids - completed - pending
    if unknown_receipts:
        errors.append(
            "step_receipts: step ids are absent from checkpoint: "
            + ", ".join(sorted(unknown_receipts))
        )
    if successful_steps != completed:
        errors.append(
            "step_receipts: successful step ids must exactly match checkpoint "
            "completed_step_ids"
        )
    if successful_steps & pending:
        errors.append("step_receipts: successful steps cannot remain pending")
    if snapshot["snapshot_digest"] != snapshot_digest(snapshot):
        errors.append("snapshot_digest: canonical digest mismatch")
    return errors


def create_run_snapshot(
    *,
    checkpoint: Mapping[str, Any],
    step_receipts: list[Mapping[str, Any]],
    state: str,
    snapshot_id: str | None = None,
    snapshot_version: int = 1,
    plan_identity: Mapping[str, Any] | None = None,
    subject_identity: Mapping[str, Any] | None = None,
    event_sequence: int = 0,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Create and validate a deterministic-content run snapshot envelope."""
    snapshot: dict[str, Any] = {
        "schema_version": "pdx_run_snapshot_v1",
        "snapshot_id": snapshot_id or f"snap_{uuid.uuid4().hex}",
        "snapshot_version": snapshot_version,
        "run_id": checkpoint.get("run_id"),
        "state": state,
        "checkpoint": deepcopy(dict(checkpoint)),
        "step_receipts": deepcopy([dict(receipt) for receipt in step_receipts]),
        "event_sequence": event_sequence,
        "created_at": created_at or datetime.now(UTC).isoformat(),
    }
    if plan_identity is not None:
        snapshot["plan_identity"] = deepcopy(dict(plan_identity))
    if subject_identity is not None:
        snapshot["subject_identity"] = deepcopy(dict(subject_identity))
    snapshot["snapshot_digest"] = snapshot_digest(snapshot)
    errors = validate_run_snapshot(snapshot)
    if errors:
        raise SnapshotError("invalid run snapshot:\n" + "\n".join(errors))
    return snapshot


def encode_run_snapshot(snapshot: Mapping[str, Any]) -> bytes:
    """Validate and encode a snapshot as bounded canonical UTF-8 JSON."""
    errors = validate_run_snapshot(snapshot)
    if errors:
        raise SnapshotError("invalid run snapshot:\n" + "\n".join(errors))
    encoded = json.dumps(
        snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise SnapshotError("run snapshot exceeds maximum encoded size")
    return encoded


def decode_run_snapshot(encoded: bytes | str) -> dict[str, Any]:
    """Decode bounded JSON and fail closed on malformed or tampered snapshots."""
    raw = encoded.encode("utf-8") if isinstance(encoded, str) else encoded
    if not isinstance(raw, bytes):
        raise SnapshotError("run snapshot must be bytes or text")
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise SnapshotError("run snapshot exceeds maximum encoded size")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError("run snapshot is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise SnapshotError("run snapshot must be a JSON object")
    errors = validate_run_snapshot(value)
    if errors:
        raise SnapshotError("invalid run snapshot:\n" + "\n".join(errors))
    return value


class InMemoryCheckpointRepository:
    """Thread-safe reference implementation with optimistic version checks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, dict[str, Any]] = {}

    def put_if_absent(self, snapshot: Mapping[str, Any]) -> bool:
        errors = validate_run_snapshot(snapshot)
        if errors:
            raise SnapshotError("invalid run snapshot:\n" + "\n".join(errors))
        snapshot_id = str(snapshot["snapshot_id"])
        with self._lock:
            if snapshot_id in self._values:
                return False
            self._values[snapshot_id] = deepcopy(dict(snapshot))
            return True

    def get(self, snapshot_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._values.get(snapshot_id)
            return deepcopy(value) if value is not None else None

    def compare_and_set(
        self,
        snapshot_id: str,
        expected_version: int,
        snapshot: Mapping[str, Any],
    ) -> bool:
        errors = validate_run_snapshot(snapshot)
        if errors:
            raise SnapshotError("invalid run snapshot:\n" + "\n".join(errors))
        if snapshot.get("snapshot_id") != snapshot_id:
            raise SnapshotError("replacement snapshot identity mismatch")
        with self._lock:
            current = self._values.get(snapshot_id)
            if current is None or current["snapshot_version"] != expected_version:
                return False
            if snapshot.get("snapshot_version") != expected_version + 1:
                raise SnapshotError("replacement snapshot version must advance by one")
            self._values[snapshot_id] = deepcopy(dict(snapshot))
            return True


class InMemoryDecisionRepository:
    """Thread-safe decision store with replay-safe dual identities."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_key: dict[str, dict[str, Any]] = {}
        self._by_checkpoint: dict[str, dict[str, Any]] = {}

    def record_once(self, decision: Mapping[str, Any]) -> dict[str, Any]:
        normalized = deepcopy(dict(decision))
        errors = _schema_errors("approval_decision.v1.schema.json", normalized)
        if errors:
            raise SnapshotError("invalid approval decision:\n" + "\n".join(errors))
        key = normalized["idempotency_key"]
        checkpoint_id = normalized["checkpoint_id"]
        with self._lock:
            existing_key = self._by_key.get(key)
            existing_checkpoint = self._by_checkpoint.get(checkpoint_id)
            for existing in (existing_key, existing_checkpoint):
                if existing is not None:
                    if existing == normalized:
                        return deepcopy(existing)
                    raise SnapshotError("approval decision identity conflict")
            self._by_key[key] = deepcopy(normalized)
            self._by_checkpoint[checkpoint_id] = deepcopy(normalized)
            return deepcopy(normalized)

    def get_by_checkpoint_id(self, checkpoint_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._by_checkpoint.get(checkpoint_id)
            return deepcopy(value) if value is not None else None

    def get_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._by_key.get(key)
            return deepcopy(value) if value is not None else None
