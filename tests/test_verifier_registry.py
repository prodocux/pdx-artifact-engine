from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pdx_artifact_engine import ArtifactRuntime
from pdx_artifact_engine.cli.validate import validate_file
from pdx_artifact_engine.registry import SkillRegistry

ROOT = Path(__file__).resolve().parents[1]


class ProductVerifier:
    @property
    def verifier_id(self) -> str:
        return "domain.rule"

    def verify(self, check, context):
        return {
            "verifier_id": self.verifier_id,
            "version": "1.0.0",
            "status": "pass",
            "reason_codes": ["RULE_PASSED"],
            "rule_set_id": "synthetic_rules",
            "rule_set_version": "1",
            "rule_digest": "a" * 64,
            "evidence_ids": ["evidence-1"],
            "details": {"score": 100},
            "timestamp": datetime.now(UTC).isoformat(),
        }


def _plan(check: str) -> dict:
    return {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "verifier-test",
        "producer": {"type": "manual"},
        "steps": [
            {
                "id": "verify",
                "kind": "verify",
                "verification": [{"id": "v", "check": check, "fail_action": "stop"}],
            }
        ],
    }


def test_registered_product_verifier_is_persisted_without_product_import(
    tmp_path,
) -> None:
    runtime = ArtifactRuntime(
        SkillRegistry([]), verifiers={"domain.rule": ProductVerifier()}
    )
    result = runtime.execute_plan(_plan("domain.rule"), tmp_path)
    verification = result["run_manifest"]["steps"][0]
    assert verification["status"] == "completed"
    persisted = result["artifact_manifest"]["verification"]
    assert persisted[0]["verifier_id"] == "domain.rule"
    assert persisted[0]["status"] == "pass"
    assert (
        result["artifact_manifest"]["provenance"][0]["outputs"]["verification"][0][
            "rule_digest"
        ]
        == "a" * 64
    )
    assert (
        validate_file(
            ROOT / "schemas/artifact_manifest.schema.json",
            tmp_path / "artifact_manifest.json",
        )
        == []
    )
    assert (
        validate_file(
            ROOT / "schemas/run_manifest.schema.json",
            tmp_path / "run_manifest.json",
        )
        == []
    )


def test_missing_verifier_fails_closed_by_default(tmp_path) -> None:
    result = ArtifactRuntime(SkillRegistry([])).execute_plan(
        _plan("domain.missing"), tmp_path
    )
    assert result["run_manifest"]["status"] == "failed"
    assert "domain.missing" in result["run_manifest"]["errors"][0]


def test_missing_verifier_review_policy_is_explicit(tmp_path) -> None:
    runtime = ArtifactRuntime(SkillRegistry([]), missing_verifier_policy="review")
    result = runtime.execute_plan(_plan("domain.missing"), tmp_path)
    assert result["run_manifest"]["status"] == "completed_with_review"


def test_invalid_verifier_result_fails_closed(tmp_path) -> None:
    class Invalid(ProductVerifier):
        def verify(self, check, context):
            return {"verifier_id": check, "status": "pass"}

    runtime = ArtifactRuntime(SkillRegistry([]), verifiers={"domain.rule": Invalid()})
    result = runtime.execute_plan(_plan("domain.rule"), tmp_path)
    assert result["run_manifest"]["status"] == "failed"
