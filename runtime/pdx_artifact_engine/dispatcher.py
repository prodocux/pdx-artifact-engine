from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import PlanError, RegistryError
from .executors import DEFAULT_EXECUTORS, mock_executor
from .manifest import build_manifest, write_manifest
from .paths import ensure_within_directory
from .registry import SkillRegistry
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
        "details": "No built-in verifier for this check in v0.1.0; marked review.",
    }


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

        try:
            ordered = order_steps(list(plan["steps"]))
        except PlanError as exc:
            run_status = "failed"
            errors.append(str(exc))
            verification: list[dict[str, str]] = []
            manifest = build_manifest(
                artifact_id=plan.get("request_id", run_id),
                artifact_type=plan.get("intent", {}).get("artifact_type", "unknown"),
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
                steps=[],
                verification=verification,
                errors=errors,
                planner=self.planner_name,
            )
            write_run_manifest(run_manifest, output_dir / "run_manifest.json")
            return {"artifact_manifest": manifest, "run_manifest": run_manifest}

        for step in ordered:
            kind = step["kind"]
            step_id = step["id"]
            name = step["name"]
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

            if kind in {"expert", "human_input"}:
                if self.allow_mock:
                    mock_inputs = dict(inputs)
                    mock_inputs["_declared_outputs"] = step.get("outputs", [])
                    result = mock_executor(mock_inputs, output_dir / step_id)
                    files = result.get("files", [])
                    artifact_files.extend((Path(path), name) for path in files)
                    outputs = result.get("outputs") or {
                        str(path.name): Path(path).as_posix() for path in files
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
                        "detail": f"{kind} mocked; replace with planner/provider in later versions",
                    })
                    if run_status == "completed":
                        run_status = "completed_with_review"
                    continue

                run_status = "blocked"
                detail = (
                    f"{kind} '{name}' requires a planner/provider or --mock; "
                    "v0.1.0 is model-optional and does not run experts by default"
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

            if kind == "verification":
                step_reports.append({
                    "step_id": step_id,
                    "kind": kind,
                    "name": name,
                    "status": "skipped",
                    "detail": "Inline verification steps are reserved; use plan.verification",
                })
                provenance.append({
                    "step_id": step_id,
                    "tool": name,
                    "inputs": inputs,
                    "outputs": {"status": "skipped"},
                })
                continue

            if kind not in {"skill", "fixture"}:
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

            skill_name = name if kind == "skill" else "pdx.fixture_stage"
            if kind == "fixture":
                skill_name = "pdx.fixture_stage"
            try:
                skill = self.registry.get(skill_name)
            except RegistryError as exc:
                run_status = "failed"
                detail = str(exc)
                errors.append(detail)
                step_reports.append({
                    "step_id": step_id,
                    "kind": kind,
                    "name": skill_name,
                    "status": "failed",
                    "detail": detail,
                })
                provenance.append({
                    "step_id": step_id,
                    "tool": skill_name,
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
                    f"Entrypoint metadata is '{skill.entrypoint}' but not auto-run in v0.1.0 "
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
                # Keep going to verification + manifest write; do not raise.
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
            for item in plan.get("verification", [])
        ]

        if any(item["status"] == "fail" for item in verification):
            if run_status in {"completed", "completed_with_review"}:
                # honor fail_action=stop as failed; repair/ask_human stays reviewable
                stopping = False
                for plan_check, result in zip(plan.get("verification", []), verification):
                    if result["status"] == "fail" and plan_check.get("fail_action") == "stop":
                        stopping = True
                        errors.append(f"Verification failed: {result['check']}")
                run_status = "failed" if stopping else "completed_with_review"
        elif any(item["status"] == "review" for item in verification):
            if run_status == "completed":
                run_status = "completed_with_review"

        manifest = build_manifest(
            artifact_id=plan["request_id"],
            artifact_type=plan["intent"]["artifact_type"],
            files=artifact_files,
            provenance=provenance,
            verification=verification,
            relative_to=output_dir,
        )
        write_manifest(manifest, output_dir / "artifact_manifest.json")
        run_manifest = build_run_manifest(
            run_id=run_id,
            request_id=plan["request_id"],
            status=run_status,
            steps=step_reports,
            verification=verification,
            errors=errors,
            planner=self.planner_name,
        )
        write_run_manifest(run_manifest, output_dir / "run_manifest.json")
        return {"artifact_manifest": manifest, "run_manifest": run_manifest}
