"""Core contract tests: schemas, state machine, v0→v1 compat."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdx_artifact_core import (
    RunState,
    can_transition,
    translate_plan_v0_to_v1,
    validate_execution_plan,
    validate_tool_request,
    validate_tool_result,
)
from pdx_artifact_core.compat_v0 import CompatError


ROOT = Path(__file__).resolve().parents[1]


def test_minimal_v1_plan_validates() -> None:
    plan = json.loads(
        (ROOT / "examples" / "plans" / "execution_plan_v1_minimal.json").read_text(
            encoding="utf-8"
        )
    )
    assert validate_execution_plan(plan) == []


def test_plan_accepts_product_neutral_producer_identifier() -> None:
    plan = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "producer-ok",
        "producer": {"type": "acme.workflow_v2", "name": "Coordinator"},
        "steps": [{"id": "approve", "kind": "approval"}],
    }
    assert validate_execution_plan(plan) == []


def test_plan_rejects_invalid_producer_identifier() -> None:
    plan = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "producer-bad",
        "producer": {"type": "Vendor Name With Spaces"},
        "steps": [{"id": "approve", "kind": "approval"}],
    }
    assert validate_execution_plan(plan)


def test_tool_step_requires_tool_field() -> None:
    plan = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "bad",
        "producer": {"type": "manual"},
        "steps": [{"id": "s1", "kind": "tool", "name": "missing_tool"}],
    }
    errs = validate_execution_plan(plan)
    assert errs


def test_per_step_approval_policy_allowed() -> None:
    plan = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "ok",
        "producer": {"type": "google_agent_builder", "name": "coord"},
        "steps": [
            {
                "id": "t1",
                "kind": "tool",
                "tool": "pdx.fixture_stage",
                "policies": {"approval_required": False},
            },
            {
                "id": "a1",
                "kind": "approval",
                "depends_on": ["t1"],
                "policies": {"approval_required": True},
            },
        ],
        "policies": {"timeout_seconds": 60, "max_retries": 1},
    }
    assert validate_execution_plan(plan) == []


def test_tool_request_and_result_schemas() -> None:
    req = {
        "schema_version": "pdx_tool_request_v1",
        "tool": "prodocux.validate_structure",
        "request_id": "r1",
        "inputs": {"document_path": "out.docx"},
    }
    assert validate_tool_request(req) == []

    result = {
        "schema_version": "pdx_tool_result_v1",
        "status": "completed",
        "outputs": {"passed": True},
        "artifacts": [{"uri": "artifact://run/out.docx", "checksum": "sha256:abc"}],
        "provenance": {"engine": "prodocux"},
        "verification": [],
        "retryable": False,
        "transport": "http",
    }
    assert validate_tool_result(result) == []


def test_state_return_edges() -> None:
    assert can_transition(RunState.AWAITING_TOOL, RunState.RUNNING)
    assert can_transition(RunState.AWAITING_APPROVAL, RunState.RUNNING)
    assert not can_transition(RunState.COMPLETED, RunState.RUNNING)


def test_translate_v0_skill_and_human_input() -> None:
    v0 = {
        "schema_version": "pdx_plan_v0",
        "request_id": "ex1",
        "intent": {"artifact_type": "doc", "summary": "t"},
        "steps": [
            {
                "id": "s1",
                "kind": "skill",
                "name": "pdx.fixture_stage",
                "inputs": {},
                "outputs": ["x"],
            },
            {
                "id": "h1",
                "kind": "human_input",
                "name": "review",
                "depends_on": ["s1"],
            },
        ],
        "verification": [],
    }
    v1 = translate_plan_v0_to_v1(v0, producer_type="manual")
    assert validate_execution_plan(v1) == []
    assert v1["steps"][0]["kind"] == "tool"
    assert v1["steps"][0]["tool"] == "pdx.fixture_stage"
    assert v1["steps"][1]["kind"] == "approval"
    assert v1["steps"][1]["policies"]["approval_required"] is True


def test_translate_rejects_expert() -> None:
    v0 = {
        "schema_version": "pdx_plan_v0",
        "request_id": "ex2",
        "intent": {"artifact_type": "doc", "summary": "t"},
        "steps": [{"id": "e1", "kind": "expert", "name": "planner"}],
        "verification": [],
    }
    with pytest.raises(CompatError, match="expert"):
        translate_plan_v0_to_v1(v0)


def test_translate_deterministic_example() -> None:
    v0 = json.loads(
        (ROOT / "examples" / "plans" / "pif_deterministic_plan.json").read_text(
            encoding="utf-8"
        )
    )
    v1 = translate_plan_v0_to_v1(v0, producer_type="rules", producer_name="fixture")
    assert validate_execution_plan(v1) == []
    assert all(s["kind"] == "tool" for s in v1["steps"])


def test_rejects_duplicate_step_ids() -> None:
    plan = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "dup",
        "producer": {"type": "manual"},
        "steps": [
            {"id": "a", "kind": "tool", "tool": "t1"},
            {"id": "a", "kind": "tool", "tool": "t2"},
        ],
    }
    errs = validate_execution_plan(plan)
    assert any("duplicate" in e for e in errs)


def test_rejects_unknown_dependency() -> None:
    plan = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "dep",
        "producer": {"type": "manual"},
        "steps": [
            {"id": "a", "kind": "tool", "tool": "t1", "depends_on": ["missing"]},
        ],
    }
    errs = validate_execution_plan(plan)
    assert any("unknown dependency" in e for e in errs)


def test_rejects_dependency_cycle() -> None:
    plan = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "cyc",
        "producer": {"type": "manual"},
        "steps": [
            {"id": "a", "kind": "tool", "tool": "t1", "depends_on": ["b"]},
            {"id": "b", "kind": "tool", "tool": "t2", "depends_on": ["a"]},
        ],
    }
    errs = validate_execution_plan(plan)
    assert any("cycle" in e for e in errs)


def test_transform_and_verify_require_fields() -> None:
    bad_transform = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "tr",
        "producer": {"type": "manual"},
        "steps": [{"id": "x", "kind": "transform"}],
    }
    assert validate_execution_plan(bad_transform)

    bad_verify = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "vf",
        "producer": {"type": "manual"},
        "steps": [{"id": "y", "kind": "verify"}],
    }
    assert validate_execution_plan(bad_verify)

    ok = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "ok",
        "producer": {"type": "manual"},
        "steps": [
            {"id": "x", "kind": "transform", "transform": "normalize_json"},
            {
                "id": "y",
                "kind": "verify",
                "depends_on": ["x"],
                "verification": [{"id": "c1", "check": "schema.valid:out"}],
            },
        ],
    }
    assert validate_execution_plan(ok) == []


def test_tool_request_result_require_schema_version() -> None:
    assert validate_tool_request(
        {"tool": "t", "request_id": "r", "inputs": {}}
    )
    assert validate_tool_result({"status": "completed"})


def test_rejects_signed_url_artifact_uri() -> None:
    from pdx_artifact_core.validate import is_forbidden_artifact_uri

    assert is_forbidden_artifact_uri(
        "https://storage.googleapis.com/b/o?X-Goog-Signature=abc"
    )
    assert is_forbidden_artifact_uri("gs://bucket/obj?X-Goog-Signature=abc")
    assert not is_forbidden_artifact_uri("gs://bucket/path/to/obj")
    assert not is_forbidden_artifact_uri("artifact://run/out.docx")

    result = {
        "schema_version": "pdx_tool_result_v1",
        "status": "completed",
        "artifacts": [
            {
                "uri": "https://storage.googleapis.com/b/o?X-Goog-Signature=deadbeef",
            }
        ],
    }
    errs = validate_tool_result(result)
    assert any("forbidden" in e for e in errs)
