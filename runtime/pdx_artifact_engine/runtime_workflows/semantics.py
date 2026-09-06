"""Runtime semantic validation beyond JSON Schema expressiveness."""

from __future__ import annotations

from typing import Any


def validate_plan(plan: dict[str, Any], computed_digest: str) -> list[str]:
    errors: list[str] = []
    steps = plan["steps"]
    ids = [step["workflow_step_id"] for step in steps]
    id_set = set(ids)
    if len(ids) != len(id_set):
        errors.append("WORKFLOW_STEP_ID_DUPLICATE")
    dependencies = {step["workflow_step_id"]: step["depends_on"] for step in steps}
    if any(dependency not in id_set for values in dependencies.values() for dependency in values):
        errors.append("WORKFLOW_DEPENDENCY_UNKNOWN")
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
    kinds = {step["workflow_step_id"]: step["step_kind"] for step in steps}
    role_producers = {
        "patch": {"builder", "repair"}, "check_report": {"check"},
        "review": {"reviewer"}, "repair_output": {"repair"},
        "supporting_evidence": {"builder", "check", "reviewer", "repair"},
    }
    edge_ids = [edge["edge_id"] for edge in plan["artifact_edges"]]
    if len(edge_ids) != len(set(edge_ids)):
        errors.append("ARTIFACT_EDGE_ID_DUPLICATE")
    for edge in plan["artifact_edges"]:
        producer = edge["producer_step_id"]
        consumer = edge["consumer_step_id"]
        if producer not in id_set or consumer not in id_set:
            errors.append("ARTIFACT_EDGE_STEP_UNKNOWN")
        if producer == consumer:
            errors.append("ARTIFACT_EDGE_SELF_REFERENCE")
        if kinds.get(producer) not in role_producers[edge["artifact_role"]]:
            errors.append("ARTIFACT_EDGE_ROLE_INVALID")
    budgets = plan["budgets"]
    provider_steps = [step for step in steps if step["step_kind"] != "check"]
    check_steps = [step for step in steps if step["step_kind"] == "check"]
    repair_steps = [step for step in steps if step["step_kind"] == "repair"]
    if sum(step["max_attempts"] for step in provider_steps) > budgets["max_provider_attempts"]:
        errors.append("WORKFLOW_PROVIDER_ATTEMPT_BUDGET_CONTRADICTION")
    if sum(step["max_attempts"] for step in check_steps) > budgets["max_check_attempts"]:
        errors.append("WORKFLOW_CHECK_ATTEMPT_BUDGET_CONTRADICTION")
    iterations = sorted(step["repair_iteration"] for step in repair_steps)
    if iterations != list(range(1, len(iterations) + 1)):
        errors.append("WORKFLOW_REPAIR_ITERATION_INVALID")
    for step in repair_steps:
        parent = step["parent_step_id"]
        if parent not in id_set or kinds.get(parent) not in {"reviewer", "repair"}:
            errors.append("WORKFLOW_REPAIR_PARENT_INVALID")
        if parent not in step["depends_on"]:
            errors.append("WORKFLOW_REPAIR_PARENT_DEPENDENCY_REQUIRED")
    if len(repair_steps) > budgets["max_repair_iterations"]:
        errors.append("WORKFLOW_REPAIR_BUDGET_CONTRADICTION")
    if len(plan["artifact_edges"]) > budgets["max_cross_step_artifact_edges"]:
        errors.append("WORKFLOW_EDGE_BUDGET_CONTRADICTION")
    if plan["plan_digest"] != computed_digest:
        errors.append("WORKFLOW_PLAN_DIGEST_INVALID")
    return sorted(set(errors))
