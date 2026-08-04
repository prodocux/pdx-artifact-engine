from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from pdx_artifact_core import translate_plan_v0_to_v1, validate_execution_plan
from pdx_artifact_core.compat_v0 import CompatError

from .errors import PlanError, RegistryError
from .executors import DEFAULT_EXECUTORS, mock_executor
from .manifest import build_manifest, write_manifest
from .paths import ensure_within_directory
from .registry import SkillDefinition, SkillRegistry
from .run_manifest import build_run_manifest, write_run_manifest

Executor = Callable[[dict[str, Any], Path], dict[str, Any]]
_REF = re.compile(r"^\$([A-Za-z0-9_\-]+)(?:\.(.+))?$")


def order_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {step["id"]: step for step in steps}
    if len(by_id) != len(steps):
        raise PlanError("Plan step ids must be unique")

    for step in steps:
        for dep in step.get("depends_on", []) or []:
            if dep not in by_id:
                raise PlanError(f"Step {step['id']} depends on unknown step '{dep}'")

    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    visiting: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in seen:
            return
        if step_id in visiting:
            raise PlanError(f"Cycle detected in depends_on at '{step_id}'")
        visiting.add(step_id)
        step = by_id[step_id]
        for dep in step.get("depends_on", []) or []:
            visit(dep)
        visiting.remove(step_id)
        seen.add(step_id)
        ordered.append(step)

    for step in steps:
        visit(step["id"])
    return ordered


def resolve_value(value: Any, context: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, str):
        match = _REF.match(value)
        if match:
            step_id, key = match.group(1), match.group(2)
            if step_id not in context:
                raise PlanError(f"Input reference '${step_id}' has no completed outputs")
            outputs = context[step_id]
            if key is None:
                return outputs
            if key not in outputs:
                raise PlanError(
                    f"Input reference '${step_id}.{key}' missing; have {sorted(outputs)}"
                )
            return outputs[key]
        return value
    if isinstance(value, list):
        return [resolve_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: resolve_value(item, context) for key, item in value.items()}
    return value


def resolve_inputs(
    inputs: dict[str, Any],
    context: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {key: resolve_value(value, context) for key, value in inputs.items()}


def evaluate_check(
    check: str,
    *,
    completed_steps: set[str],
    output_dir: Path,
) -> dict[str, str]:
    if check.startswith("step_completed:"):
        step_id = check.split(":", 1)[1]
        if step_id in completed_steps:
            return {
                "check": check,
                "status": "pass",
                "details": f"Step {step_id} completed",
            }
        return {
            "check": check,
            "status": "fail",
            "details": f"Step {step_id} did not complete",
        }

    if check.startswith("file_exists:"):
        rel = check.split(":", 1)[1]
        try:
            path = ensure_within_directory(output_dir, rel, label="file_exists check")
        except PlanError as exc:
            return {
                "check": check,
                "status": "fail",
                "details": str(exc),
            }
        if path.is_file():
            return {"check": check, "status": "pass", "details": f"Found {rel}"}
        return {"check": check, "status": "fail", "details": f"Missing {rel}"}

    if check.startswith("always_review:"):
        return {
            "check": check,
            "status": "review",
            "details": check.split(":", 1)[1],
        }

    return {
        "check": check,
        "status": "review",
        "details": "No built-in verifier for this check; marked review.",
    }


def normalize_plan_to_v1(
    plan: dict[str, Any],
    *,
    allow_mock: bool = False,
    planner_name: str = "manual",
) -> dict[str, Any]:
    """Return an execution-plan v1 dict. Raises PlanError on hard failures."""
    version = plan.get("schema_version")
    if version == "pdx_execution_plan_v1":
        errs = validate_execution_plan(plan)
        if errs:
            raise PlanError("Invalid v1 plan:\n" + "\n".join(f"- {e}" for e in errs))
        return plan

    if version != "pdx_plan_v0":
        raise PlanError(f"Unsupported plan schema_version: {version!r}")

    working = deepcopy(plan)
    for step in working.get("steps") or []:
        if step.get("kind") != "expert":
            continue
        if not allow_mock:
            raise PlanError(
                f"legacy expert step '{step.get('id')}' has no Core equivalent; "
                "resolve in orchestrator or pass --mock for demo-only rewrite to tool"
            )
        # Demo-only: rewrite expert → skill so translate yields tool + mock path
        step["kind"] = "skill"
        step.setdefault("name", "pdx.mock_expert")

    producer_type = "rules" if planner_name == "rule" else "manual"
    try:
        translated = translate_plan_v0_to_v1(
            working,
            producer_type=producer_type,
            producer_name=planner_name,
        )
    except CompatError as exc:
        raise PlanError(str(exc)) from exc

    errs = validate_execution_plan(translated)
    if errs:
        raise PlanError(
            "Translated v0 plan is invalid v1:\n"
            + "\n".join(f"- {error}" for error in errs)
        )
    return translated


def _step_display_name(step: dict[str, Any]) -> str:
    if step.get("name"):
        return str(step["name"])
    if step.get("tool"):
        return str(step["tool"])
    if step.get("transform"):
        return str(step["transform"])
    return str(step.get("id", "step"))


def _approval_required(step: dict[str, Any], plan: dict[str, Any]) -> bool:
    policies = step.get("policies") or {}
    if "approval_required" in policies:
        return bool(policies["approval_required"])
    plan_policies = plan.get("policies") or {}
    if "default_approval_required" in plan_policies:
        return bool(plan_policies["default_approval_required"])
    return step.get("kind") == "approval"


class Dispatcher:
    def __init__(
        self,
        registry: SkillRegistry,
        executors: dict[str, Executor] | None = None,
        *,
        allow_mock: bool = False,
        planner_name: str = "manual",
    ) -> None:
        merged = dict(DEFAULT_EXECUTORS)
        if executors:
            merged.update(executors)
        self.registry = registry
        self.executors = merged
        self.allow_mock = allow_mock
        self.planner_name = planner_name

    def _empty_failure(
        self,
        plan: dict[str, Any],
        output_dir: Path,
        *,
        run_id: str,
        run_status: str,
        errors: list[str],
        step_reports: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        verification: list[dict[str, str]] = []
        intent = plan.get("intent") or {}
        manifest = build_manifest(
            artifact_id=str(plan.get("request_id", run_id)),
            artifact_type=str(intent.get("artifact_type", "unknown")),
            files=[],
            provenance=[],
            verification=verification,
            relative_to=output_dir,
        )
        write_manifest(manifest, output_dir / "artifact_manifest.json")
        run_manifest = build_run_manifest(
            run_id=run_id,
            request_id=str(plan.get("request_id", run_id)),
            status=run_status,
            steps=step_reports or [],
            verification=verification,
            errors=errors,
            planner=self.planner_name,
        )
        write_run_manifest(run_manifest, output_dir / "run_manifest.json")
        return {"artifact_manifest": manifest, "run_manifest": run_manifest}

    def run(self, plan: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        provenance: list[dict[str, Any]] = []
        artifact_files: list[tuple[Path, str]] = []
        step_reports: list[dict[str, Any]] = []
        context: dict[str, dict[str, Any]] = {}
        completed_steps: set[str] = set()
        errors: list[str] = []
        run_status = "completed"
        original_plan = plan

        # Expert without mock → blocked (preserve v0.1 semantics / D3)
        if plan.get("schema_version") == "pdx_plan_v0" and not self.allow_mock:
            for step in plan.get("steps") or []:
                if step.get("kind") == "expert":
                    detail = (
                        f"expert '{step.get('name', step.get('id'))}' requires a "
                        "planner/provider or --mock; Core has no expert step kind (D3)"
                    )
                    return self._empty_failure(
                        plan,
                        output_dir,
                        run_id=run_id,
                        run_status="blocked",
                        errors=[detail],
                        step_reports=[
                            {
                                "step_id": step["id"],
                                "kind": "expert",
                                "name": step.get("name", step["id"]),
                                "status": "blocked",
                                "detail": detail,
                            }
                        ],
                    )

        try:
            plan = normalize_plan_to_v1(
                plan,
                allow_mock=self.allow_mock,
                planner_name=self.planner_name,
            )
        except PlanError as exc:
            status = "blocked" if "expert" in str(exc).lower() else "failed"
            return self._empty_failure(
                original_plan,
                output_dir,
                run_id=run_id,
                run_status=status,
                errors=[str(exc)],
            )

        try:
            ordered = order_steps(list(plan["steps"]))
        except PlanError as exc:
            return self._empty_failure(
                plan,
                output_dir,
                run_id=run_id,
                run_status="failed",
                errors=[str(exc)],
            )

        for step in ordered:
            kind = step["kind"]
            step_id = step["id"]
            name = _step_display_name(step)
            try:
                inputs = resolve_inputs(step.get("inputs", {}) or {}, context)
            except PlanError as exc:
                run_status = "failed"
                errors.append(str(exc))
                step_reports.append({
                    "step_id": step_id,
                    "kind": kind,
                    "name": name,
                    "status": "failed",
                    "detail": str(exc),
                })
                break

            if kind == "approval":
                if self.allow_mock or not _approval_required(step, plan):
                    mock_inputs = dict(inputs)
                    mock_inputs["_declared_outputs"] = step.get("outputs", [])
                    result = mock_executor(mock_inputs, output_dir / step_id)
                    files = result.get("files", [])
                    artifact_files.extend((Path(path), name) for path in files)
                    outputs = result.get("outputs") or {
                        str(Path(path).name): Path(path).as_posix() for path in files
                    }
                    context[step_id] = outputs
                    completed_steps.add(step_id)
                    provenance.append({
                        "step_id": step_id,
                        "tool": name,
                        "inputs": inputs,
                        "outputs": {"status": "mocked", "outputs": outputs},
                    })
                    step_reports.append({
                        "step_id": step_id,
                        "kind": kind,
                        "name": name,
                        "status": "mocked",
                        "detail": "approval mocked or not required",
                    })
                    if run_status == "completed":
                        run_status = "completed_with_review"
                    continue

                run_status = "blocked"
                detail = (
                    f"approval '{name}' requires human approval or --mock "
                    "(awaiting_approval)"
                )
                errors.append(detail)
                provenance.append({
                    "step_id": step_id,
                    "tool": name,
                    "inputs": inputs,
                    "outputs": {"status": "blocked", "reason": detail},
                })
                step_reports.append({
                    "step_id": step_id,
                    "kind": kind,
                    "name": name,
                    "status": "blocked",
                    "detail": detail,
                })
                break

            if kind == "verify":
                # Inline verify steps: run listed checks; do not auto-complete step
                step_checks = []
                for item in step.get("verification") or []:
                    step_checks.append(
                        evaluate_check(
                            item["check"],
                            completed_steps=completed_steps,
                            output_dir=output_dir,
                        )
                    )
                failed = [c for c in step_checks if c["status"] == "fail"]
                if failed:
                    run_status = "failed"
                    for item in failed:
                        errors.append(f"Verify step {step_id}: {item['check']}")
                    step_reports.append({
                        "step_id": step_id,
                        "kind": kind,
                        "name": name,
                        "status": "failed",
                        "detail": str(failed),
                    })
                    break
                completed_steps.add(step_id)
                context[step_id] = {"verification": step_checks}
                step_reports.append({
                    "step_id": step_id,
                    "kind": kind,
                    "name": name,
                    "status": "completed",
                    "detail": "ok",
                })
                provenance.append({
                    "step_id": step_id,
                    "tool": name,
                    "inputs": inputs,
                    "outputs": {"status": "completed", "verification": step_checks},
                })
                continue

            if kind == "transform":
                # No built-in transforms yet — mock or fail
                transform_id = step.get("transform") or name
                if self.allow_mock:
                    mock_inputs = dict(inputs)
                    mock_inputs["_declared_outputs"] = step.get("outputs", [])
                    result = mock_executor(mock_inputs, output_dir / step_id)
                    files = result.get("files", [])
                    artifact_files.extend((Path(path), transform_id) for path in files)
                    outputs = result.get("outputs") or {
                        str(Path(path).name): Path(path).as_posix() for path in files
                    }
                    context[step_id] = outputs
                    completed_steps.add(step_id)
                    step_reports.append({
                        "step_id": step_id,
                        "kind": kind,
                        "name": transform_id,
                        "status": "mocked",
                        "detail": "transform mocked",
                    })
                    if run_status == "completed":
                        run_status = "completed_with_review"
                    continue
                detail = f"No transform executor for '{transform_id}'"
                run_status = "failed"
                errors.append(detail)
                step_reports.append({
                    "step_id": step_id,
                    "kind": kind,
                    "name": transform_id,
                    "status": "failed",
                    "detail": detail,
                })
                break

            if kind != "tool":
                detail = f"Unsupported step kind '{kind}'"
                run_status = "failed"
                errors.append(detail)
                step_reports.append({
                    "step_id": step_id,
                    "kind": kind,
                    "name": name,
                    "status": "failed",
                    "detail": detail,
                })
                break

            tool_name = str(step.get("tool") or name)
            skill: Any = None
            try:
                skill = self.registry.get(tool_name)
            except RegistryError as exc:
                # Demo-only rewrite of legacy expert → pdx.mock_expert (not in registry)
                if self.allow_mock and tool_name == "pdx.mock_expert":
                    skill = SkillDefinition(
                        name="pdx.mock_expert",
                        version="0",
                        domain="compat",
                        description="Demo-only stand-in for legacy expert steps",
                        entrypoint="mock",
                        inputs=(),
                        outputs=tuple(step.get("outputs") or ()),
                        artifacts=tuple(step.get("outputs") or ()),
                        failure_codes=({"code": "MOCK", "meaning": "mock"},),
                        verification_hooks=(),
                    )
                else:
                    run_status = "failed"
                    detail = str(exc)
                    errors.append(detail)
                    step_reports.append({
                        "step_id": step_id,
                        "kind": kind,
                        "name": tool_name,
                        "status": "failed",
                        "detail": detail,
                    })
                    provenance.append({
                        "step_id": step_id,
                        "tool": tool_name,
                        "inputs": inputs,
                        "outputs": {"status": "failed", "error": detail},
                    })
                    break

            executor = self.executors.get(skill.name)
            mocked = False
            if executor is None and self.allow_mock:
                executor = mock_executor
                mocked = True
            if executor is None:
                detail = (
                    f"No executor registered for skill '{skill.name}'. "
                    f"Entrypoint metadata is '{skill.entrypoint}' but not auto-run "
                    "unless you register an executor or pass --mock."
                )
                run_status = "failed"
                errors.append(detail)
                step_reports.append({
                    "step_id": step_id,
                    "kind": kind,
                    "name": skill.name,
                    "status": "failed",
                    "detail": detail,
                })
                provenance.append({
                    "step_id": step_id,
                    "tool": skill.name,
                    "inputs": inputs,
                    "outputs": {"status": "failed", "error": detail},
                })
                break

            try:
                exec_inputs = dict(inputs)
                if mocked:
                    exec_inputs["_declared_outputs"] = list(
                        step.get("outputs") or skill.outputs
                    )
                result = executor(exec_inputs, output_dir / step_id)
            except Exception as exc:
                run_status = "failed"
                detail = f"Step {step_id} failed: {exc}"
                errors.append(detail)
                step_reports.append({
                    "step_id": step_id,
                    "kind": kind,
                    "name": skill.name,
                    "status": "failed",
                    "detail": detail,
                })
                provenance.append({
                    "step_id": step_id,
                    "tool": skill.name,
                    "inputs": inputs,
                    "outputs": {"status": "failed", "error": detail},
                })
                break

            files = result.get("files", [])
            artifact_files.extend((Path(path), skill.name) for path in files)
            outputs = result.get("outputs")
            if not isinstance(outputs, dict):
                outputs = {Path(path).name: Path(path).as_posix() for path in files}
            context[step_id] = outputs
            completed_steps.add(step_id)
            provenance.append({
                "step_id": step_id,
                "tool": skill.name,
                "inputs": inputs,
                "outputs": (
                    result.get("result")
                    if isinstance(result.get("result"), dict)
                    else {"status": "completed", "outputs": outputs}
                ),
            })
            step_reports.append({
                "step_id": step_id,
                "kind": kind,
                "name": skill.name,
                "status": "mocked" if mocked else "completed",
                "detail": "ok",
            })
            if mocked and run_status == "completed":
                run_status = "completed_with_review"

        verification = [
            evaluate_check(
                item["check"],
                completed_steps=completed_steps,
                output_dir=output_dir,
            )
            for item in plan.get("verification", []) or []
        ]

        if any(item["status"] == "fail" for item in verification):
            if run_status in {"completed", "completed_with_review"}:
                stopping = False
                for plan_check, result in zip(
                    plan.get("verification", []) or [], verification
                ):
                    if result["status"] == "fail" and plan_check.get("fail_action") == "stop":
                        stopping = True
                        errors.append(f"Verification failed: {result['check']}")
                run_status = "failed" if stopping else "completed_with_review"
        elif any(item["status"] == "review" for item in verification):
            if run_status == "completed":
                run_status = "completed_with_review"

        intent = plan.get("intent") or original_plan.get("intent") or {}
        manifest = build_manifest(
            artifact_id=str(plan.get("request_id") or original_plan.get("request_id")),
            artifact_type=str(intent.get("artifact_type", "unknown")),
            files=artifact_files,
            provenance=provenance,
            verification=verification,
            relative_to=output_dir,
        )
        write_manifest(manifest, output_dir / "artifact_manifest.json")
        run_manifest = build_run_manifest(
            run_id=run_id,
            request_id=str(plan.get("request_id") or original_plan.get("request_id")),
            status=run_status,
            steps=step_reports,
            verification=verification,
            errors=errors,
            planner=self.planner_name,
        )
        write_run_manifest(run_manifest, output_dir / "run_manifest.json")
        return {"artifact_manifest": manifest, "run_manifest": run_manifest}
