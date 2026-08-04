"""Product-neutral ArtifactRuntime tests."""

from __future__ import annotations

from pathlib import Path

from pdx_artifact_engine import ArtifactRuntime
from pdx_artifact_engine.registry import SkillRegistry

ROOT = Path(__file__).resolve().parents[1]


def _registry() -> SkillRegistry:
    return SkillRegistry.load(
        ROOT / "skills" / "registry.sample.json",
        schema_path=ROOT / "schemas" / "skill_registry.schema.json",
    )


def test_artifact_runtime_execute_plan(tmp_path: Path) -> None:
    registry = _registry()
    runtime = ArtifactRuntime(registry, allow_mock=True)
    plan = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "rt_001",
        "producer": {"type": "manual"},
        "intent": {"artifact_type": "test", "summary": "rt"},
        "steps": [
            {
                "id": "stage",
                "kind": "tool",
                "tool": "pdx.fixture_stage",
                "inputs": {
                    "fixtures": {
                        "drafts": str(ROOT / "examples/fixtures/pif_demo/drafts.json"),
                    }
                },
                "outputs": ["drafts.json"],
            }
        ],
        "verification": [],
    }
    result = runtime.execute_plan(plan, tmp_path)
    assert result["run_manifest"]["status"] in {"completed", "completed_with_review"}
