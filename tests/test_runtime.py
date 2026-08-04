import json
from pathlib import Path

import pytest

from pdx_artifact_engine.dispatcher import Dispatcher, order_steps
from pdx_artifact_engine.errors import PlanError, RegistryError
from pdx_artifact_engine.plan import load_plan
from pdx_artifact_engine.planners import RulePlanner
from pdx_artifact_engine.registry import SkillRegistry


ROOT = Path(__file__).resolve().parents[1]


def test_registry_loads_known_skills() -> None:
    registry = SkillRegistry.load(
        ROOT / "skills" / "registry.sample.json",
        schema_path=ROOT / "schemas" / "skill_registry.schema.json",
    )
    assert "prodocux.pdf_extract" in registry.names()
    assert "pdx.fixture_stage" in registry.names()
    assert registry.get("freecad.generate_cad").domain == "3d"
    assert registry.get("prodocux.pdf_extract").failure_codes


def test_registry_rejects_duplicate_names(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    skill = {
        "name": "duplicate",
        "version": "1",
        "domain": "test",
        "description": "test",
        "entrypoint": "test",
        "inputs": [],
        "outputs": [],
        "failure_codes": [{"code": "X", "meaning": "x"}],
    }
    registry_path.write_text(json.dumps({
        "schema_version": "pdx_skill_registry_v0",
        "skills": [skill, skill],
    }), encoding="utf-8")
    with pytest.raises(RegistryError, match="Duplicate"):
        SkillRegistry.load(registry_path)


def test_order_steps_respects_depends_on() -> None:
    steps = [
        {"id": "b", "kind": "skill", "name": "x", "depends_on": ["a"]},
        {"id": "a", "kind": "skill", "name": "x"},
    ]
    ordered = order_steps(steps)
    assert [step["id"] for step in ordered] == ["a", "b"]


def test_order_steps_rejects_unknown_dependency() -> None:
    with pytest.raises(PlanError, match="unknown step"):
        order_steps([
            {"id": "a", "kind": "skill", "name": "x", "depends_on": ["missing"]},
        ])


def test_deterministic_plan_runs_without_llm(tmp_path: Path) -> None:
    registry = SkillRegistry.load(
        ROOT / "skills" / "registry.sample.json",
        schema_path=ROOT / "schemas" / "skill_registry.schema.json",
    )
    plan = load_plan(
        ROOT / "examples" / "plans" / "pif_deterministic_plan.json",
        ROOT / "schemas" / "plan.schema.json",
    )
    # Rewrite fixture paths to absolute so the test is cwd-independent.
    fixtures = plan["steps"][0]["inputs"]["fixtures"]
    plan["steps"][0]["inputs"]["fixtures"] = {
        key: str(ROOT / value) for key, value in fixtures.items()
    }
    result = Dispatcher(registry, allow_mock=True, planner_name="manual").run(plan, tmp_path)
    run_manifest = result["run_manifest"]
    assert run_manifest["status"] in {"completed", "completed_with_review"}
    assert (tmp_path / "run_manifest.json").is_file()
    assert (tmp_path / "artifact_manifest.json").is_file()
    assert (tmp_path / "stage_fixtures" / "drafts.json").is_file()
    assert any(item["status"] == "pass" for item in run_manifest["verification"])


def test_expert_step_blocks_without_mock(tmp_path: Path) -> None:
    registry = SkillRegistry.load(
        ROOT / "skills" / "registry.sample.json",
        schema_path=ROOT / "schemas" / "skill_registry.schema.json",
    )

    def pdf_executor(inputs: dict, output_dir: Path) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "pages.json"
        path.write_text("{}", encoding="utf-8")
        return {
            "result": {"status": "ok"},
            "files": [path],
            "outputs": {"pages.json": path.as_posix()},
        }

    plan = load_plan(
        ROOT / "examples" / "plans" / "pif_workflow_plan.json",
        ROOT / "schemas" / "plan.schema.json",
    )
    result = Dispatcher(
        registry,
        executors={"prodocux.pdf_extract": pdf_executor},
        allow_mock=False,
    ).run(plan, tmp_path)
    assert result["run_manifest"]["status"] == "blocked"


def test_rule_planner_builds_deterministic_plan() -> None:
    request = {
        "request_id": "rule_test",
        "artifact_type": "regulatory_document_package",
        "summary": "test",
        "fixtures": {
            "drafts": str(ROOT / "examples/fixtures/pif_demo/drafts.json"),
            "pages": str(ROOT / "examples/fixtures/pif_demo/pages.json"),
        },
    }
    plan = RulePlanner().create_plan(request)
    assert plan["schema_version"] == "pdx_plan_v0"
    assert plan["steps"][0]["name"] == "pdx.fixture_stage"


def _assert_manifests_valid(tmp_path: Path) -> None:
    from pdx_artifact_engine.cli.validate import validate_file

    assert validate_file(
        ROOT / "schemas" / "run_manifest.schema.json",
        tmp_path / "run_manifest.json",
    ) == []
    assert validate_file(
        ROOT / "schemas" / "artifact_manifest.schema.json",
        tmp_path / "artifact_manifest.json",
    ) == []


def test_path_traversal_rejected_in_file_exists(tmp_path: Path) -> None:
    registry = SkillRegistry.load(
        ROOT / "skills" / "registry.sample.json",
        schema_path=ROOT / "schemas" / "skill_registry.schema.json",
    )
    plan = {
        "schema_version": "pdx_plan_v0",
        "request_id": "trav_001",
        "intent": {"artifact_type": "test", "summary": "traversal"},
        "steps": [
            {
                "id": "stage",
                "kind": "skill",
                "name": "pdx.fixture_stage",
                "inputs": {
                    "fixtures": {
                        "drafts": str(ROOT / "examples/fixtures/pif_demo/drafts.json"),
                    }
                },
                "outputs": ["drafts"],
            }
        ],
        "verification": [
            {
                "id": "evil",
                "check": "file_exists:../secret.txt",
                "fail_action": "stop",
            }
        ],
    }
    result = Dispatcher(registry, allow_mock=False).run(plan, tmp_path)
    checks = {item["check"]: item for item in result["run_manifest"]["verification"]}
    assert checks["file_exists:../secret.txt"]["status"] == "fail"
    assert "traversal" in checks["file_exists:../secret.txt"]["details"].lower() or ".." in checks["file_exists:../secret.txt"]["details"]
    _assert_manifests_valid(tmp_path)


def test_path_traversal_rejected_in_mock_output_name(tmp_path: Path) -> None:
    registry = SkillRegistry.load(
        ROOT / "skills" / "registry.sample.json",
        schema_path=ROOT / "schemas" / "skill_registry.schema.json",
    )

    def evil_inputs_executor(inputs: dict, output_dir: Path) -> dict:
        from pdx_artifact_engine.executors import mock_executor

        return mock_executor(
            {**inputs, "_declared_outputs": ["../../evil.json"]},
            output_dir,
        )

    plan = {
        "schema_version": "pdx_plan_v0",
        "request_id": "trav_002",
        "intent": {"artifact_type": "test", "summary": "mock traversal"},
        "steps": [
            {
                "id": "s1",
                "kind": "skill",
                "name": "prodocux.pif_audit",
                "inputs": {},
                "outputs": ["../../evil.json"],
            }
        ],
        "verification": [],
    }
    result = Dispatcher(
        registry,
        executors={"prodocux.pif_audit": evil_inputs_executor},
        allow_mock=False,
    ).run(plan, tmp_path)
    assert result["run_manifest"]["status"] == "failed"
    assert any("traversal" in err.lower() or "Unsafe" in err for err in result["run_manifest"]["errors"])
    assert not (tmp_path.parent / "evil.json").exists()
    _assert_manifests_valid(tmp_path)


def test_unknown_skill_writes_failed_manifests(tmp_path: Path) -> None:
    registry = SkillRegistry.load(
        ROOT / "skills" / "registry.sample.json",
        schema_path=ROOT / "schemas" / "skill_registry.schema.json",
    )
    plan = {
        "schema_version": "pdx_plan_v0",
        "request_id": "unknown_skill_001",
        "intent": {"artifact_type": "test", "summary": "unknown"},
        "steps": [
            {
                "id": "boom",
                "kind": "skill",
                "name": "does.not.exist",
                "inputs": {},
                "outputs": ["x.json"],
            }
        ],
        "verification": [
            {"id": "done", "check": "step_completed:boom", "fail_action": "stop"}
        ],
    }
    result = Dispatcher(registry, allow_mock=True).run(plan, tmp_path)
    assert result["run_manifest"]["status"] == "failed"
    assert "Unknown skill" in result["run_manifest"]["errors"][0]
    assert (tmp_path / "run_manifest.json").is_file()
    assert (tmp_path / "artifact_manifest.json").is_file()
    _assert_manifests_valid(tmp_path)


def test_cycle_detection() -> None:
    with pytest.raises(PlanError, match="Cycle detected"):
        order_steps([
            {"id": "a", "kind": "skill", "name": "x", "depends_on": ["b"]},
            {"id": "b", "kind": "skill", "name": "x", "depends_on": ["a"]},
        ])


def test_cycle_in_plan_writes_failed_manifests(tmp_path: Path) -> None:
    registry = SkillRegistry.load(
        ROOT / "skills" / "registry.sample.json",
        schema_path=ROOT / "schemas" / "skill_registry.schema.json",
    )
    plan = {
        "schema_version": "pdx_plan_v0",
        "request_id": "cycle_001",
        "intent": {"artifact_type": "test", "summary": "cycle"},
        "steps": [
            {"id": "a", "kind": "skill", "name": "pdx.fixture_stage", "depends_on": ["b"], "inputs": {}},
            {"id": "b", "kind": "skill", "name": "pdx.fixture_stage", "depends_on": ["a"], "inputs": {}},
        ],
        "verification": [],
    }
    result = Dispatcher(registry).run(plan, tmp_path)
    assert result["run_manifest"]["status"] == "failed"
    assert any("cycle" in err.lower() for err in result["run_manifest"]["errors"])
    _assert_manifests_valid(tmp_path)


def test_executor_exception_writes_valid_failed_manifests(tmp_path: Path) -> None:
    registry = SkillRegistry.load(
        ROOT / "skills" / "registry.sample.json",
        schema_path=ROOT / "schemas" / "skill_registry.schema.json",
    )

    def boom(inputs: dict, output_dir: Path) -> dict:
        raise RuntimeError("executor exploded")

    plan = {
        "schema_version": "pdx_plan_v0",
        "request_id": "exec_fail_001",
        "intent": {"artifact_type": "test", "summary": "exception"},
        "steps": [
            {
                "id": "s1",
                "kind": "skill",
                "name": "prodocux.pif_audit",
                "inputs": {},
                "outputs": ["audit.json"],
            }
        ],
        "verification": [
            {"id": "done", "check": "step_completed:s1", "fail_action": "stop"}
        ],
    }
    result = Dispatcher(
        registry,
        executors={"prodocux.pif_audit": boom},
        allow_mock=False,
    ).run(plan, tmp_path)
    assert result["run_manifest"]["status"] == "failed"
    assert any("executor exploded" in err for err in result["run_manifest"]["errors"])
    assert result["run_manifest"]["steps"][0]["status"] == "failed"
    _assert_manifests_valid(tmp_path)
