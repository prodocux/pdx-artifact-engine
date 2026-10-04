"""Contract tests for the additive ER-002 parent-workflow erratum candidate."""

from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "docs" / "runtime-provider-workflow" / "schemas"
ERRATUM = ROOT / "docs" / "dynamic-dispatch" / "erratum-001"
SCHEMAS = ERRATUM / "schemas"
EXAMPLES = ERRATUM / "examples"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry() -> Registry:
    registry = Registry()
    for path in [*PARENT.glob("*.json"), *SCHEMAS.glob("*.json")]:
        schema = _load(path)
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(path.name, resource)
        registry = registry.with_resource(schema["$id"], resource)
    return registry


def _errors(schema_name: str, value: dict) -> list:
    return list(
        Draft202012Validator(
            _load(SCHEMAS / schema_name),
            registry=_registry(),
            format_checker=FormatChecker(),
        ).iter_errors(value)
    )


def test_five_erratum_schemas_are_valid_and_examples_conform() -> None:
    schemas = list(SCHEMAS.glob("*.json"))
    assert len(schemas) == 5
    for path in schemas:
        Draft202012Validator.check_schema(_load(path))

    cases = {
        "workflow-plan-v2.valid.json": "pdx_runtime_provider_workflow_plan_v2.schema.json",
        "workflow-create-request-v2.valid.json": "pdx_runtime_provider_workflow_create_request_v2.schema.json",
        "workflow-state-v2.valid.json": "pdx_runtime_provider_workflow_state_v2.schema.json",
        "workflow-receipt-v2.valid.json": "pdx_runtime_provider_workflow_receipt_v2.schema.json",
        "route-mapping-v2.valid.json": "pdx_runtime_provider_route_mapping_v2.schema.json",
    }
    for example, schema in cases.items():
        assert not _errors(schema, _load(EXAMPLES / example)), example


def test_frozen_v1_plan_rejects_dispatch_while_v2_requires_authority_binding() -> None:
    plan = _load(EXAMPLES / "workflow-plan-v2.valid.json")
    v1 = _load(PARENT / "pdx_runtime_provider_workflow_plan_v1.schema.json")
    assert list(Draft202012Validator(v1).iter_errors(plan))

    invalid = deepcopy(plan)
    del invalid["steps"][1]["dispatch_policy_id"]
    assert _errors("pdx_runtime_provider_workflow_plan_v2.schema.json", invalid)


def test_v2_retains_runstate_and_terminal_error_boundary() -> None:
    state = _load(EXAMPLES / "workflow-state-v2.valid.json")
    state["state"] = "budget_exhausted"
    assert _errors("pdx_runtime_provider_workflow_state_v2.schema.json", state)

    state = _load(EXAMPLES / "workflow-state-v2.valid.json")
    state["terminal_error"] = {
        "schema_version": "pdx_runtime_provider_workflow_error_v1",
        "code": "WORKFLOW_BUDGET_EXHAUSTED",
        "message": "budget exhausted",
        "retryable": False,
        "reconcile_required": False,
    }
    assert _errors("pdx_runtime_provider_workflow_state_v2.schema.json", state)


def test_successful_dispatch_requires_immutable_dispatch_receipt_artifact() -> None:
    receipt = _load(EXAMPLES / "workflow-receipt-v2.valid.json")
    del receipt["step_receipts"][1]["dispatch_receipt_artifact"]
    assert _errors("pdx_runtime_provider_workflow_receipt_v2.schema.json", receipt)


def test_route_mapping_preserves_operations_paths_and_v1_bindings() -> None:
    program = """
import fs from 'node:fs';
import {validateRouteMappingV2} from './docs/dynamic-dispatch/erratum-001/semantic-validator.mjs';
const candidate = JSON.parse(fs.readFileSync('./docs/dynamic-dispatch/erratum-001/examples/route-mapping-v2.valid.json', 'utf8'));
const frozen = JSON.parse(fs.readFileSync('./docs/runtime-provider-workflow/route-mapping.json', 'utf8'));
validateRouteMappingV2(candidate, frozen);
const drift = structuredClone(candidate); drift.routes[0].path += '/caller-selects-v2';
try { validateRouteMappingV2(drift, frozen); process.exit(2); } catch (error) { if (error.code !== 'ROUTE_WIRE_IDENTITY_CHANGED') throw error; }
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_erratum_semantics_reject_budget_role_binding_and_receipt_drift() -> None:
    program = """
import fs from 'node:fs';
import {computePlanDigest, validatePlanV2, validatePolicyPlanBinding, validateReceiptV2, validateStateAgainstPlan} from './docs/dynamic-dispatch/erratum-001/semantic-validator.mjs';
const load = (name) => JSON.parse(fs.readFileSync(`./docs/dynamic-dispatch/erratum-001/examples/${name}`, 'utf8'));
const expect = (fn, code) => { try { fn(); throw new Error(`accepted ${code}`); } catch (error) { if (error.code !== code) throw error; } };
const plan = load('workflow-plan-v2.valid.json');
validatePlanV2(plan);
validateStateAgainstPlan(load('workflow-state-v2.valid.json'), plan);
validateReceiptV2(load('workflow-receipt-v2.valid.json'));
const policy = JSON.parse(fs.readFileSync('./docs/dynamic-dispatch/examples/policy.valid.json', 'utf8'));
validatePolicyPlanBinding(plan, policy);
const budget = structuredClone(plan); budget.budgets.max_dispatch_attempts = 0; budget.plan_digest = computePlanDigest(budget);
expect(() => validatePlanV2(budget), 'WORKFLOW_DISPATCH_ATTEMPT_BUDGET_CONTRADICTION');
const role = structuredClone(plan); role.artifact_edges[1].producer_step_id = 'step_decision_001'; role.plan_digest = computePlanDigest(role);
expect(() => validatePlanV2(role), 'ARTIFACT_EDGE_ROLE_INVALID');
const mismatch = structuredClone(policy); mismatch.run_a_plan_digest = 'f'.repeat(64);
expect(() => validatePolicyPlanBinding(plan, mismatch), 'DISPATCH_PLAN_POLICY_BINDING_INVALID');
const receipt = load('workflow-receipt-v2.valid.json'); receipt.artifact_edges[1].artifact.sha256 = 'f'.repeat(64);
expect(() => validateReceiptV2(receipt), 'ARTIFACT_IDENTITY_DIGEST_INVALID');
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_candidate_manifest_locks_erratum_and_frozen_v1_bytes() -> None:
    manifest = _load(ERRATUM / "candidate-manifest.v1.json")
    assert manifest["status"] == "bilateral_review_candidate"
    assert manifest["freeze_authorized"] is False
    assert manifest["implementation_authorized"] is False
    assert manifest["release_version"] is None

    gap = manifest["endorsed_gap_analysis"]
    assert hashlib.sha256((ERRATUM / gap["path"]).resolve().read_bytes()).hexdigest() == gap["sha256"]
    addendum = manifest["route_authority_addendum"]
    assert addendum["status"] == "bilateral_review_required"
    assert hashlib.sha256((ERRATUM / addendum["path"]).resolve().read_bytes()).hexdigest() == addendum["sha256"]
    for name, expected in manifest["schemas"].items():
        assert hashlib.sha256((SCHEMAS / name).read_bytes()).hexdigest() == expected
    for name, expected in manifest["evidence"].items():
        assert hashlib.sha256((ERRATUM / name).read_bytes()).hexdigest() == expected
    for name, expected in manifest["frozen_v1_byte_identity"].items():
        assert hashlib.sha256((PARENT / name).read_bytes()).hexdigest() == expected


def test_erratum_freeze_locks_reviewed_candidate_and_route_authority() -> None:
    freeze = _load(ERRATUM / "erratum-freeze.v1.json")
    assert freeze["status"] == "frozen"
    assert freeze["implementation_authorized"] is True
    assert freeze["release_version"] is None

    parent = freeze["parent_freeze"]
    assert hashlib.sha256((ERRATUM / parent["manifest_path"]).resolve().read_bytes()).hexdigest() == parent["manifest_sha256"]
    candidate = freeze["reviewed_candidate"]
    assert hashlib.sha256((ERRATUM / candidate["path"]).read_bytes()).hexdigest() == candidate["sha256"]
    for relative, expected in freeze["authority_documents"].items():
        assert hashlib.sha256((ERRATUM / relative).resolve().read_bytes()).hexdigest() == expected
    for filename, expected in freeze["schemas"].items():
        assert hashlib.sha256((SCHEMAS / filename).read_bytes()).hexdigest() == expected
    for relative, expected in freeze["evidence"].items():
        assert hashlib.sha256((ERRATUM / relative).read_bytes()).hexdigest() == expected
    for relative, expected in freeze["frozen_v1_route_authority"].items():
        assert hashlib.sha256((ERRATUM / relative).resolve().read_bytes()).hexdigest() == expected
