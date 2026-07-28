from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Protocol

from .errors import PlanError
from .plan import load_plan


class Planner(Protocol):
    """Compile a user request into a PDX plan. Implementations must not require LLM weights."""

    name: str

    def create_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return a plan document conforming to plan.schema.json."""


class ManualPlanner:
    """Load a plan that was authored offline (human, Codex, or external tool)."""

    name = "manual"

    def __init__(self, plan_path: Path, schema_path: Path) -> None:
        self.plan_path = plan_path
        self.schema_path = schema_path

    def create_plan(self, request: dict[str, Any] | None = None) -> dict[str, Any]:
        del request
        return load_plan(self.plan_path, self.schema_path)


class RulePlanner:
    """Deterministic planner for a small set of known intents. No model weights."""

    name = "rule"

    def __init__(self, templates_dir: Path | None = None) -> None:
        self.templates_dir = templates_dir

    def create_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        artifact_type = request.get("artifact_type")
        request_id = str(request.get("request_id") or "rule_plan_001")
        summary = str(request.get("summary") or "Rule-generated deterministic plan")

        if artifact_type == "regulatory_document_package":
            fixtures = request.get("fixtures")
            if not isinstance(fixtures, dict):
                raise PlanError(
                    "RulePlanner for regulatory_document_package requires request.fixtures"
                )
            return {
                "schema_version": "pdx_plan_v0",
                "request_id": request_id,
                "intent": {
                    "artifact_type": artifact_type,
                    "summary": summary,
                    "risk_level": request.get("risk_level", "regulated"),
                },
                "steps": [
                    {
                        "id": "stage_fixtures",
                        "kind": "skill",
                        "name": "pdx.fixture_stage",
                        "inputs": {"fixtures": fixtures},
                        "outputs": ["drafts", "pages"],
                    },
                    {
                        "id": "assemble_docx",
                        "kind": "skill",
                        "name": "prodocux.doc_assemble",
                        "depends_on": ["stage_fixtures"],
                        "inputs": {
                            "drafts": "$stage_fixtures.drafts",
                            "pages": "$stage_fixtures.pages",
                            "template": request.get("template", "template.docx"),
                        },
                        "outputs": ["output.docx"],
                    },
                    {
                        "id": "audit_pif",
                        "kind": "skill",
                        "name": "prodocux.pif_audit",
                        "depends_on": ["assemble_docx"],
                        "inputs": {"docx": "$assemble_docx.output.docx"},
                        "outputs": ["pif_audit.json"],
                    },
                ],
                "verification": [
                    {
                        "id": "fixtures_staged",
                        "check": "step_completed:stage_fixtures",
                        "fail_action": "stop",
                    },
                    {
                        "id": "assemble_done",
                        "check": "step_completed:assemble_docx",
                        "fail_action": "stop",
                    },
                    {
                        "id": "audit_done",
                        "check": "step_completed:audit_pif",
                        "fail_action": "stop",
                    },
                ],
            }

        raise PlanError(
            f"RulePlanner has no template for artifact_type={artifact_type!r}. "
            "Supply a manual plan or extend the rule table."
        )


class ExternalPlanner:
    """Reserved for remote/HTTP planners. Not implemented in v0.1.0."""

    name = "external"

    def create_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        del request
        raise PlanError(
            "ExternalPlanner is not implemented in v0.1.0. "
            "Use ManualPlanner or RulePlanner, or provide --plan."
        )


class LlamaCppPlanner:
    """Reserved for local GGUF / llama.cpp providers. Not implemented in v0.1.0."""

    name = "llama_cpp"

    def create_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        del request
        raise PlanError(
            "LlamaCppPlanner is reserved for v0.2.0+. "
            "No model weights ship with this repository."
        )


def clone_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(plan)
