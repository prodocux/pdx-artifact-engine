"""Stable, product-neutral façade over Dispatcher."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from pdx_artifact_core import (
    EventSink,
    SnapshotError,
    StorageAdapter,
    Verifier,
    build_resumed_plan,
    run_event,
    validate_run_snapshot,
)

from .dispatcher import Dispatcher, resolve_value
from .registry import SkillDefinition, SkillRegistry

Executor = Callable[[dict[str, Any], Path], dict[str, Any]]
_OUTPUT_REF = re.compile(r"^\$([A-Za-z0-9_\-]+)(?:\.(.+))?$")


def _materialize_completed_value(
    value: Any, context: dict[str, dict[str, Any]]
) -> Any:
    if isinstance(value, str):
        match = _OUTPUT_REF.match(value)
        if match and match.group(1) in context:
            return deepcopy(resolve_value(value, context))
        return value
    if isinstance(value, list):
        return [_materialize_completed_value(item, context) for item in value]
    if isinstance(value, dict):
        return {
            key: _materialize_completed_value(item, context)
            for key, item in value.items()
        }
    return value


def _resolved_artifact_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    try:
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SnapshotError("resolved artifact value is not canonically encodable") from exc


class ArtifactRuntime:
    """Execute a validated (or v0-translatable) plan and write manifests.

    Product applications own planning; this class only runs deterministic steps
    through explicitly registered executors.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        executors: Mapping[str, Executor] | None = None,
        *,
        allow_mock: bool = False,
        planner_name: str = "manual",
        verifiers: Mapping[str, Verifier] | None = None,
        missing_verifier_policy: str = "fail",
        storage: StorageAdapter | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.registry = registry
        self.allow_mock = allow_mock
        self.planner_name = planner_name
        self.event_sink = event_sink
        self.storage = storage
        self._dispatcher = Dispatcher(
            registry,
            dict(executors) if executors else None,
            allow_mock=allow_mock,
            planner_name=planner_name,
            verifiers=dict(verifiers or {}),
            missing_verifier_policy=missing_verifier_policy,
            storage=storage,
        )

    def execute_plan(
        self,
        plan: dict[str, Any],
        output_dir: str | Path,
    ) -> dict[str, Any]:
        """Run ``plan`` into ``output_dir``; return artifact + run manifests."""
        request_id = str(plan.get("request_id", "unknown"))
        correlation_id = str(plan.get("correlation_id", request_id))
        idempotency_key = str(plan.get("idempotency_key", request_id))
        if self.event_sink:
            self.event_sink.emit(
                run_event(
                    event_type="RUN_STARTED",
                    request_id=request_id,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    status="started",
                )
            )
        result = self._dispatcher.run(plan, Path(output_dir))
        if self.event_sink:
            self.event_sink.emit(
                run_event(
                    event_type="RUN_FINISHED",
                    request_id=request_id,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    status=str(result["run_manifest"]["status"]),
                )
            )
        return result

    def resume_plan(
        self,
        plan: dict[str, Any],
        checkpoint: Mapping[str, Any],
        decision: Mapping[str, Any],
        output_dir: str | Path,
    ) -> dict[str, Any]:
        """Execute only checkpoint-pending steps after an approved decision."""
        resumed = build_resumed_plan(plan, checkpoint, decision)
        return self._dispatcher.run(resumed, Path(output_dir))

    def resume_snapshot(
        self,
        plan: dict[str, Any],
        snapshot: Mapping[str, Any],
        decision: Mapping[str, Any],
        output_dir: str | Path,
    ) -> dict[str, Any]:
        """Resume pending steps using durable bindings from a valid snapshot."""
        errors = validate_run_snapshot(snapshot)
        if errors:
            raise SnapshotError("invalid run snapshot:\n" + "\n".join(errors))
        if snapshot["state"] != "awaiting_approval":
            raise SnapshotError("only an awaiting_approval snapshot may resume")
        if snapshot["checkpoint"]["status"] != "pending":
            raise SnapshotError("only a pending checkpoint may resume")
        if any(
            receipt["status"] == "unknown_outcome"
            or bool((receipt.get("error") or {}).get("reconcile_required"))
            for receipt in snapshot["step_receipts"]
        ):
            raise SnapshotError(
                "snapshot contains an ambiguous step outcome; reconciliation is required"
            )
        resumed = build_resumed_plan(plan, snapshot["checkpoint"], decision)

        context: dict[str, dict[str, Any]] = {}
        for receipt in snapshot["step_receipts"]:
            if receipt["status"] not in {"completed", "completed_with_review"}:
                continue
            outputs: dict[str, Any] = {}
            for binding in receipt.get("output_bindings", []):
                if self.storage is None:
                    raise SnapshotError(
                        "snapshot output bindings require a configured storage adapter"
                    )
                artifact = binding["artifact"]
                uri = artifact["uri"]
                if not self.storage.exists(uri):
                    raise SnapshotError(f"snapshot artifact is unavailable: {uri}")
                value = self.storage.resolve(uri)
                materialized = _resolved_artifact_bytes(value)
                if len(materialized) != artifact["size_bytes"]:
                    raise SnapshotError(f"snapshot artifact size mismatch: {uri}")
                if hashlib.sha256(materialized).hexdigest() != artifact["sha256"]:
                    raise SnapshotError(f"snapshot artifact digest mismatch: {uri}")
                outputs[binding["name"]] = value
            context[receipt["step_id"]] = outputs

        for step in resumed["steps"]:
            step["inputs"] = _materialize_completed_value(
                step.get("inputs", {}) or {}, context
            )
        return self._dispatcher.run(resumed, Path(output_dir))


def skill_definition(
    *,
    name: str,
    domain: str,
    description: str,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
) -> SkillDefinition:
    """Minimal registry entry for dry-run / adapter tools."""
    outs = outputs or ["result.json"]
    return SkillDefinition(
        name=name,
        version="0.0.0-dryrun",
        domain=domain,
        description=description,
        entrypoint="artifact_runtime:registered_executor",
        inputs=tuple(inputs or []),
        outputs=tuple(outs),
        artifacts=tuple(outs),
        failure_codes=({"code": "DRYRUN_FAIL", "meaning": "dry-run executor failed"},),
        verification_hooks=(),
    )
