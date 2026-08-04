"""Dispatcher v1 kinds + v0 translate path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdx_artifact_engine.dispatcher import Dispatcher, normalize_plan_to_v1
from pdx_artifact_engine.errors import PlanError
from pdx_artifact_engine.registry import SkillRegistry

ROOT = Path(__file__).resolve().parents[1]


def _registry() -> SkillRegistry:
    return SkillRegistry.load(
        ROOT / "skills" / "registry.sample.json",
        schema_path=ROOT / "schemas" / "skill_registry.schema.json",
    )


def test_normalize_v0_skill_to_tool() -> None:
    plan = {
        "schema_version": "pdx_plan_v0",
        "request_id": "n1",
        "intent": {"artifact_type": "t", "summary": "s"},
        "steps": [
            {
                "id": "s1",
                "kind": "skill",
                "name": "pdx.fixture_stage",
                "inputs": {},
                "outputs": ["a.json"],
            }
        ],
        "verification": [],
    }
    v1 = normalize_plan_to_v1(plan)
    assert v1["schema_version"] == "pdx_execution_plan_v1"
    assert v1["steps"][0]["kind"] == "tool"
    assert v1["steps"][0]["tool"] == "pdx.fixture_stage"


def test_normalize_v0_revalidates_translated_v1_semantics() -> None:
    plan = {
        "schema_version": "pdx_plan_v0",
        "request_id": "invalid-translated-verify",
        "steps": [{"id": "verify", "kind": "verification"}],
    }
    with pytest.raises(PlanError, match="Translated v0 plan is invalid v1"):
        normalize_plan_to_v1(plan)


def test_v1_tool_plan_runs(tmp_path: Path) -> None:
    registry = _registry()
    plan = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "v1_run_001",
        "producer": {"type": "manual", "name": "test"},
        "intent": {"artifact_type": "test", "summary": "v1"},
        "steps": [
            {
                "id": "stage",
                "kind": "tool",
                "tool": "pdx.fixture_stage",
                "inputs": {
                    "fixtures": {
                        "drafts": str(
                            ROOT / "examples/fixtures/pif_demo/drafts.json"
                        ),
                    }
                },
                "outputs": ["drafts.json"],
            }
        ],
        "verification": [
            {
                "id": "f",
                "check": "file_exists:stage/drafts.json",
                "fail_action": "stop",
            }
        ],
    }
    result = Dispatcher(registry, allow_mock=False).run(plan, tmp_path)
    assert result["run_manifest"]["status"] in {"completed", "completed_with_review"}
    assert result["run_manifest"]["steps"][0]["kind"] == "tool"
    assert (tmp_path / "stage" / "drafts.json").is_file()


def test_approval_blocks_without_mock(tmp_path: Path) -> None:
    registry = _registry()
    plan = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "appr_001",
        "producer": {"type": "manual"},
        "intent": {"artifact_type": "test", "summary": "approval"},
        "steps": [
            {
                "id": "gate",
                "kind": "approval",
                "name": "human_gate",
                "policies": {"approval_required": True},
                "inputs": {},
            }
        ],
        "verification": [],
    }
    result = Dispatcher(registry, allow_mock=False).run(plan, tmp_path)
    assert result["run_manifest"]["status"] == "blocked"


def test_validate_structure_tool_via_mock_http(tmp_path: Path) -> None:
    from pdx_adapter_prodocux import ValidateStructureExecutor
    from pdx_adapter_prodocux.http_client import ProDocuXHttpClient

    class _FakeResp:
        def __init__(self) -> None:
            self.status = 200
            self._raw = json.dumps(
                {
                    "kernel_version": "test",
                    "passed": True,
                    "invariants": [],
                }
            ).encode("utf-8")

        def read(self) -> bytes:
            return self._raw

        def getcode(self) -> int:
            return 200

        def __enter__(self) -> "_FakeResp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    client = ProDocuXHttpClient(
        "http://example.test/v1",
        opener=lambda req, timeout=0: _FakeResp(),
    )
    registry = _registry()
    plan = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "vs_001",
        "producer": {"type": "manual"},
        "intent": {"artifact_type": "test", "summary": "vs"},
        "steps": [
            {
                "id": "vs",
                "kind": "tool",
                "tool": "prodocux.validate_structure",
                "inputs": {"document_path": str(tmp_path / "x.docx")},
                "outputs": ["validate_structure.json"],
            }
        ],
        "verification": [
            {
                "id": "done",
                "check": "step_completed:vs",
                "fail_action": "stop",
            }
        ],
    }
    result = Dispatcher(
        registry,
        executors={"prodocux.validate_structure": ValidateStructureExecutor(client)},
        allow_mock=False,
    ).run(plan, tmp_path)
    assert result["run_manifest"]["status"] in {"completed", "completed_with_review"}
    assert (tmp_path / "vs" / "validate_structure.json").is_file()
