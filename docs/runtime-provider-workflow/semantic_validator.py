"""Draft-only semantic validator for runtime provider workflow plans.

This module is contract evidence. It is not imported by the packaged runtime.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _assert_i_json_strings(value: Any) -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError("canonical_json_invalid")
    elif isinstance(value, list):
        for item in value:
            _assert_i_json_strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _assert_i_json_strings(key)
            _assert_i_json_strings(item)


def _canonical_bytes(value: Any) -> bytes:
    _assert_i_json_strings(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def compute_plan_digest(plan: dict[str, Any]) -> str:
    """Hash the schema-constrained I-JSON plan without its digest field."""
    payload = {key: value for key, value in plan.items() if key != "plan_digest"}
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def compute_artifact_identity_digest(identity: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(identity)).hexdigest()


def validate_receipt_semantics(receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    step_keys = {
        (item.get("workflow_step_id"), item.get("attempt_number"))
        for item in receipt.get("step_receipts", [])
    }
    edge_artifacts: dict[str, dict[str, Any]] = {}
    for edge in receipt.get("artifact_edges", []):
        artifact = edge.get("artifact", {})
        artifact_id = artifact.get("artifact_id")
        if edge.get("artifact_identity_digest") != compute_artifact_identity_digest(
            artifact
        ):
            errors.append("ARTIFACT_IDENTITY_DIGEST_INVALID")
        if artifact_id in edge_artifacts and edge_artifacts[artifact_id] != artifact:
            errors.append("ARTIFACT_RECORD_CONFLICT")
        edge_artifacts[artifact_id] = artifact

    for step in receipt.get("step_receipts", []):
        if step.get("step_kind") == "check" and step.get("status") == "succeeded":
            report = step.get("verified_check_report_artifact", {})
            if edge_artifacts.get(report.get("artifact_id")) != report:
                errors.append("CHECK_REPORT_EDGE_REQUIRED")

    for record in receipt.get("authority_records", []):
        if record.get("authority_kind") in {
            "provider_recommendation",
            "reviewer_recommendation",
        } and (record.get("workflow_step_id"), record.get("attempt_number")) not in step_keys:
            errors.append("AUTHORITY_RECOMMENDATION_ATTEMPT_UNKNOWN")
    return sorted(set(errors))


def validate_plan_semantics(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    steps = plan.get("steps", [])
    budgets = plan.get("budgets", {})
    edges = plan.get("artifact_edges", [])
    ids = [step.get("workflow_step_id") for step in steps]
    id_set = set(ids)

    if len(ids) != len(id_set):
        errors.append("WORKFLOW_STEP_ID_DUPLICATE")

    dependencies: dict[str, list[str]] = {}
    for step in steps:
        step_id = step.get("workflow_step_id")
        deps = step.get("depends_on", [])
        dependencies[step_id] = deps
        if any(dep not in id_set for dep in deps):
            errors.append("WORKFLOW_DEPENDENCY_UNKNOWN")
        if step_id in deps:
            errors.append("WORKFLOW_DEPENDENCY_CYCLE")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            errors.append("WORKFLOW_DEPENDENCY_CYCLE")
            return
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in dependencies.get(step_id, []):
            if dependency in id_set:
                visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in id_set:
        visit(step_id)

    kinds = {step.get("workflow_step_id"): step.get("step_kind") for step in steps}
    role_producers = {
        "patch": {"builder", "repair"},
        "check_report": {"check"},
        "review": {"reviewer"},
        "repair_output": {"repair"},
        "supporting_evidence": {"builder", "check", "reviewer", "repair"},
    }
    edge_ids = [edge.get("edge_id") for edge in edges]
    if len(edge_ids) != len(set(edge_ids)):
        errors.append("ARTIFACT_EDGE_ID_DUPLICATE")
    for edge in edges:
        producer = edge.get("producer_step_id")
        consumer = edge.get("consumer_step_id")
        role = edge.get("artifact_role")
        if producer not in id_set or consumer not in id_set:
            errors.append("ARTIFACT_EDGE_STEP_UNKNOWN")
        if producer == consumer:
            errors.append("ARTIFACT_EDGE_SELF_REFERENCE")
        if role in role_producers and kinds.get(producer) not in role_producers[role]:
            errors.append("ARTIFACT_EDGE_ROLE_INVALID")

    provider_steps = [step for step in steps if step.get("step_kind") != "check"]
    check_steps = [step for step in steps if step.get("step_kind") == "check"]
    repair_steps = [step for step in steps if step.get("step_kind") == "repair"]
    repair_iterations = [step.get("repair_iteration") for step in repair_steps]
    if len(repair_iterations) != len(set(repair_iterations)) or sorted(
        repair_iterations
    ) != list(range(1, len(repair_iterations) + 1)):
        errors.append("WORKFLOW_REPAIR_ITERATION_INVALID")
    for step in repair_steps:
        parent = step.get("parent_step_id")
        if parent not in id_set or kinds.get(parent) not in {"reviewer", "repair"}:
            errors.append("WORKFLOW_REPAIR_PARENT_INVALID")
        if parent not in step.get("depends_on", []):
            errors.append("WORKFLOW_REPAIR_PARENT_DEPENDENCY_REQUIRED")
    if sum(step.get("max_attempts", 0) for step in provider_steps) > budgets.get(
        "max_provider_attempts", -1
    ):
        errors.append("WORKFLOW_PROVIDER_ATTEMPT_BUDGET_CONTRADICTION")
    if sum(step.get("max_attempts", 0) for step in check_steps) > budgets.get(
        "max_check_attempts", -1
    ):
        errors.append("WORKFLOW_CHECK_ATTEMPT_BUDGET_CONTRADICTION")
    if len(repair_steps) > budgets.get("max_repair_iterations", -1):
        errors.append("WORKFLOW_REPAIR_BUDGET_CONTRADICTION")
    if len(edges) > budgets.get("max_cross_step_artifact_edges", -1):
        errors.append("WORKFLOW_EDGE_BUDGET_CONTRADICTION")
    if plan.get("plan_digest") != compute_plan_digest(plan):
        errors.append("WORKFLOW_PLAN_DIGEST_INVALID")
    return sorted(set(errors))


def validate_route_mapping_semantics(mapping: dict[str, Any]) -> list[str]:
    required = {
        "create", "get_state", "get_plan", "cancel", "reconcile",
        "claim_provider", "renew_provider_lease", "update_provider",
        "claim_check", "renew_check_lease", "update_check", "get_receipt",
    }
    operations = [route.get("operation") for route in mapping.get("routes", [])]
    errors: list[str] = []
    if set(operations) != required or len(operations) != len(required):
        errors.append("ROUTE_OPERATION_SET_INVALID")
    return errors


def activation_binding(request: dict[str, Any], kind: str) -> tuple[Any, ...]:
    """Return the immutable authority binding behind an idempotency key."""
    fields = [
        "workflow_step_id", "execution_constraints_digest", "workspace_ref",
    ]
    if kind == "provider":
        fields += ["invocation_id", "provider_id", "provider_instance_id"]
    return tuple(request.get(field) for field in fields)


def validate_activation(
    plan: dict[str, Any], workflow_state: str, request: dict[str, Any], kind: str,
    *, authenticated: bool, authorized: bool = True,
    step_state: str = "ready", existing: dict[str, Any] | None = None,
) -> list[str]:
    """Validate the preconditions that the implementation must check atomically."""
    if not authenticated:
        return ["ACTIVATION_AUTH_REQUIRED"]
    if not authorized:
        return ["ACTIVATION_AUTH_FORBIDDEN"]
    if workflow_state not in {"pending", "running"}:
        return ["WORKFLOW_NOT_ACTIVE"]
    step = next(
        (item for item in plan.get("steps", [])
         if item.get("workflow_step_id") == request.get("workflow_step_id")),
        None,
    )
    if step is None or step_state != "ready":
        return ["STEP_NOT_READY"]
    actual_kind = step.get("step_kind")
    if (kind == "check") != (actual_kind == "check"):
        return ["STEP_KIND_MISMATCH"]
    if existing is not None:
        if existing.get("kind") != kind or existing.get("binding") != activation_binding(
            request, kind
        ):
            return ["ACTIVATION_BINDING_CONFLICT"]
        if existing.get("invocation_id") not in {None, request.get("invocation_id")}:
            return ["ACTIVATION_BINDING_CONFLICT"]
    return []


def activation_transition(
    counters: dict[str, int], existing: dict[str, Any] | None,
    request: dict[str, Any], kind: str, new_token_digest: str,
) -> dict[str, Any]:
    """Evidence model: create once, or rotate the one lease for an exact retry."""
    result = {"counters": dict(counters), "invalidated_token_digest": None}
    if existing is None:
        counter = "check_attempts" if kind == "check" else "provider_attempts"
        result["counters"][counter] += 1
        result["attempt_number"] = result["counters"][counter]
    else:
        result["attempt_number"] = existing["attempt_number"]
        result["invalidated_token_digest"] = existing["lease_token_digest"]
    result["lease_token_digest"] = new_token_digest
    result["binding"] = activation_binding(request, kind)
    return result
