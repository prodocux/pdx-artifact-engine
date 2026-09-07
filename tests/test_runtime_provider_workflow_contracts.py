"""Frozen authoritative contracts for the additive runtime provider workflow."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "runtime-provider-workflow"
SCHEMAS = CONTRACT / "schemas"


def _semantic_module():
    path = CONTRACT / "semantic_validator.py"
    spec = importlib.util.spec_from_file_location("workflow_semantics", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _load(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def _registry() -> Registry:
    registry = Registry()
    for path in SCHEMAS.glob("*.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(path.name, Resource.from_contents(schema))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


def _errors(schema_name: str, instance: dict) -> list[str]:
    validator = Draft202012Validator(
        _load(schema_name),
        registry=_registry(),
        format_checker=FormatChecker(),
    )
    return [error.message for error in validator.iter_errors(instance)]


def _read(folder: str, name: str) -> dict:
    return json.loads((CONTRACT / folder / name).read_text(encoding="utf-8"))


def test_all_frozen_schemas_are_valid_draft_2020_12() -> None:
    for path in SCHEMAS.glob("*.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_authoritative_examples_validate() -> None:
    cases = {
        "workflow-plan.valid.json": "pdx_runtime_provider_workflow_plan_v1.schema.json",
        "workflow-state.valid.json": "pdx_runtime_provider_workflow_state_v1.schema.json",
        "workflow-receipt.valid.json": "pdx_runtime_provider_workflow_receipt_v1.schema.json",
    }
    for example, schema in cases.items():
        assert _errors(schema, _read("examples", example)) == [], example

    route_mapping = json.loads((CONTRACT / "route-mapping.json").read_text())
    assert _errors(
        "pdx_runtime_provider_route_mapping_v1.schema.json", route_mapping
    ) == []
    assert _semantic_module().validate_route_mapping_semantics(route_mapping) == []


def test_check_step_cannot_carry_provider_operation_identity() -> None:
    errors = _errors(
        "pdx_runtime_provider_workflow_plan_v1.schema.json",
        _read("negative", "plan.check-with-provider-operation.json"),
    )
    assert errors


def test_reviewer_recommendation_cannot_be_encoded_as_approval() -> None:
    errors = _errors(
        "pdx_runtime_provider_workflow_receipt_v1.schema.json",
        _read("negative", "receipt.peer-approval.json"),
    )
    assert errors


def test_successful_check_requires_verified_report_artifact() -> None:
    errors = _errors(
        "pdx_runtime_provider_workflow_receipt_v1.schema.json",
        _read("negative", "receipt.check-success-without-report.json"),
    )
    assert errors


def test_error_codes_are_closed_and_bounded() -> None:
    errors = _errors(
        "pdx_runtime_provider_workflow_error_v1.schema.json",
        _read("negative", "error.unknown-code.json"),
    )
    assert errors


def test_runstate_and_terminal_error_conditions_are_locked() -> None:
    state_schema = _load("pdx_runtime_provider_workflow_state_v1.schema.json")
    receipt_schema = _load("pdx_runtime_provider_workflow_receipt_v1.schema.json")
    assert "budget_exhausted" not in json.dumps(state_schema)
    assert "budget_exhausted" not in json.dumps(receipt_schema)

    running = _read("examples", "workflow-state.valid.json")
    running["terminal_error"] = {
        "schema_version": "pdx_runtime_provider_workflow_error_v1",
        "code": "WORKFLOW_BUDGET_EXHAUSTED",
        "message": "budget exceeded",
        "retryable": False,
        "reconcile_required": False,
    }
    assert _errors("pdx_runtime_provider_workflow_state_v1.schema.json", running)

    failed = deepcopy(running)
    failed["state"] = "failed"
    failed.pop("terminal_error")
    assert _errors("pdx_runtime_provider_workflow_state_v1.schema.json", failed)


def test_receipt_binds_full_artifact_identity_and_nine_counters() -> None:
    semantics = _semantic_module()
    receipt = _read("examples", "workflow-receipt.valid.json")
    assert semantics.validate_receipt_semantics(receipt) == []
    report = receipt["step_receipts"][1]["verified_check_report_artifact"]
    assert set(report) == {
        "schema_version", "artifact_id", "uri", "sha256", "size_bytes", "media_type"
    }
    assert len(receipt["final_counters"]) == 9
    assert "repair_iterations" in receipt["final_counters"]

    corrupted = deepcopy(receipt)
    corrupted["artifact_edges"][0]["artifact"]["sha256"] = "f" * 64
    assert "ARTIFACT_IDENTITY_DIGEST_INVALID" in semantics.validate_receipt_semantics(
        corrupted
    )

    missing_edge = deepcopy(receipt)
    missing_edge["artifact_edges"] = []
    assert "CHECK_REPORT_EDGE_REQUIRED" in semantics.validate_receipt_semantics(
        missing_edge
    )


def test_frozen_schemas_are_packaged_without_modifying_published_contracts() -> None:
    runtime_contracts = ROOT / "runtime" / "pdx_artifact_engine" / "contracts"
    packaged = runtime_contracts / "runtime_provider_workflow"
    assert packaged.is_dir()
    frozen = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in SCHEMAS.glob("*.json")
    }
    packaged_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in packaged.glob("*.json")
    }
    assert {name: packaged_hashes[name] for name in frozen} == frozen
    assert set(packaged_hashes) - set(frozen) == {
        "pdx_runtime_provider_step_projection_v1.schema.json"
    }
    text = (CONTRACT / "README.md").read_text(encoding="utf-8")
    assert "Production implementation was separately authorized" in text


def test_collective_controls_are_workflow_level_not_handshake_extensions() -> None:
    plan = _load("pdx_runtime_provider_workflow_plan_v1.schema.json")
    required_budgets = {
        "max_provider_attempts", "max_check_attempts", "max_concurrent_steps",
        "max_repair_iterations", "max_total_runtime_seconds",
        "max_total_event_bytes", "max_total_artifact_bytes",
        "max_cross_step_artifact_edges", "max_external_operations",
    }
    assert required_budgets == set(plan["properties"]["budgets"]["required"])
    assert "artifact_edges" in plan["required"]


def test_plan_semantic_positive_and_negative_fixtures() -> None:
    semantics = _semantic_module()
    valid = _read("examples", "workflow-plan.valid.json")
    assert semantics.validate_plan_semantics(valid) == []
    cases = _read("negative", "semantic-plan-cases.json")
    for case in cases:
        plan = deepcopy(valid)
        mutation = case["mutation"]
        if mutation == "duplicate_step":
            plan["steps"].append(deepcopy(plan["steps"][0]))
        elif mutation == "unknown_dependency":
            plan["steps"][0]["depends_on"] = ["step_missing"]
        elif mutation == "dependency_cycle":
            plan["steps"][0]["depends_on"] = ["step_reviewer"]
        elif mutation == "unknown_edge_step":
            plan["artifact_edges"][0]["consumer_step_id"] = "step_missing"
        elif mutation == "invalid_edge_role":
            plan["artifact_edges"][0]["artifact_role"] = "check_report"
        elif mutation == "provider_budget_contradiction":
            plan["budgets"]["max_provider_attempts"] = 2
        elif mutation == "check_budget_contradiction":
            plan["budgets"]["max_check_attempts"] = 0
        elif mutation == "repair_budget_contradiction":
            plan["budgets"]["max_repair_iterations"] = 0
        elif mutation == "edge_budget_contradiction":
            plan["budgets"]["max_cross_step_artifact_edges"] = 1
        elif mutation == "invalid_digest":
            plan["plan_digest"] = "f" * 64
        elif mutation == "repair_iteration_non_contiguous":
            plan["steps"][3]["repair_iteration"] = 2
        elif mutation == "repair_parent_unknown":
            plan["steps"][3]["parent_step_id"] = "step_missing"
        elif mutation == "repair_parent_not_dependency":
            plan["steps"][3]["depends_on"] = ["step_builder"]
        errors = semantics.validate_plan_semantics(plan)
        assert case["expected"] in errors, case["case"]

    unused_concurrency = deepcopy(valid)
    unused_concurrency["budgets"]["max_concurrent_steps"] = 64
    unused_concurrency["plan_digest"] = semantics.compute_plan_digest(unused_concurrency)
    assert semantics.validate_plan_semantics(unused_concurrency) == []


def test_pdx_owned_wire_surface_is_complete_and_credential_free() -> None:
    required = {
        "pdx_runtime_provider_workflow_create_request_v1.schema.json",
        "pdx_runtime_provider_workflow_create_response_v1.schema.json",
        "pdx_runtime_provider_claim_request_v1.schema.json",
        "pdx_runtime_provider_claim_request_v2.schema.json",
        "pdx_runtime_provider_claim_v1.schema.json",
        "pdx_runtime_provider_update_v1.schema.json",
        "pdx_runtime_check_claim_request_v1.schema.json",
        "pdx_runtime_check_claim_request_v2.schema.json",
        "pdx_runtime_check_claim_v1.schema.json",
        "pdx_runtime_check_update_v1.schema.json",
        "pdx_runtime_provider_record_v1.schema.json",
        "pdx_runtime_provider_route_mapping_v1.schema.json",
        "pdx_runtime_check_record_v1.schema.json",
        "pdx_runtime_workflow_cancel_v1.schema.json",
        "pdx_runtime_workflow_reconcile_v1.schema.json",
        "pdx_runtime_provider_lease_renew_v1.schema.json",
        "pdx_runtime_check_lease_renew_v1.schema.json",
        "pdx_runtime_lease_renew_response_v1.schema.json",
    }
    assert required <= {path.name for path in SCHEMAS.glob("*.json")}
    for name in required:
        text = (SCHEMAS / name).read_text(encoding="utf-8")
        assert "credential_ref" not in text
        assert "credential_value" not in text


def test_check_event_mapping_is_lossless() -> None:
    semantics = _semantic_module()
    binding_fields = {
        "workflow_job_id", "workflow_step_id", "step_kind", "claim_id",
        "lease_token", "attempt_number", "check_definition_digest",
        "execution_constraints_digest", "idempotency_key",
    }
    for name in (
        "check-event-mapping.valid.json",
        "check-outcome-mapping.valid.json",
    ):
        fixture = _read("examples", name)
        source = fixture["source"]
        target = fixture["target"]
        record = target["record"]
        assert source["payload"] == record["payload"]
        assert all(source[field] == target[field] for field in binding_fields)
        assert source["sequence"] == record["sequence"]
        assert source["payload_record_id"] == record["record_id"]
        assert source["payload_digest"] == record["payload_digest"]
        assert source["payload_digest"] == hashlib.sha256(
            semantics._canonical_bytes(source["payload"])
        ).hexdigest()
        assert _errors(
            "pdx_runtime_check_update_v1.schema.json", target
        ) == []


def test_opaque_uri_dot_segments_are_rejected() -> None:
    common = _load("pdx_runtime_provider_common_v1.schema.json")
    workspace = common["$defs"]["workspaceRef"]
    artifact = common["$defs"]["artifactRef"]
    validator = Draft202012Validator(workspace)
    assert list(validator.iter_errors("workspace://root/../other"))
    assert list(validator.iter_errors("workspace://root/./other"))
    validator = Draft202012Validator(artifact)
    assert list(validator.iter_errors("artifact://root/../other"))
    assert list(validator.iter_errors("artifact://root/./other"))


def test_route_error_codes_are_serializable_by_error_schema() -> None:
    mapping = json.loads((CONTRACT / "route-mapping.json").read_text(encoding="utf-8"))
    codes = {
        code
        for key in ("authorization_codes", "conflict_codes", "gone_codes", "too_large_codes")
        for code in mapping["http_semantics"][key]
    }
    for code in codes:
        document = {
            "schema_version": "pdx_runtime_provider_workflow_error_v1",
            "code": code,
            "message": "bounded safe error",
            "retryable": False,
            "reconcile_required": False,
        }
        assert _errors("pdx_runtime_provider_workflow_error_v1.schema.json", document) == []


def test_route_operations_are_present_exactly_once() -> None:
    semantics = _semantic_module()
    mapping = json.loads((CONTRACT / "route-mapping.json").read_text(encoding="utf-8"))
    assert semantics.validate_route_mapping_semantics(mapping) == []
    duplicate = deepcopy(mapping)
    duplicate["routes"][-1]["operation"] = duplicate["routes"][0]["operation"]
    assert semantics.validate_route_mapping_semantics(duplicate) == [
        "ROUTE_OPERATION_SET_INVALID"
    ]


def test_canonical_vectors_and_unpaired_surrogates() -> None:
    semantics = _semantic_module()
    vectors = json.loads(
        (CONTRACT / "canonicalization-vectors.v1.json").read_text(encoding="utf-8")
    )
    for vector in vectors:
        canonical = json.dumps(
            vector["input"], ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":"),
        )
        assert canonical == vector["canonical"], vector["name"]
        if "sha256" in vector:
            assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == vector["sha256"]
    invalid = json.loads(
        (CONTRACT / "canonicalization-invalid-vectors.v1.json").read_text(encoding="utf-8")
    )
    for vector in invalid:
        value = json.loads(vector["encoded_json"])
        try:
            semantics._canonical_bytes(value)
        except ValueError as error:
            assert str(error) == vector["code"]
        else:
            raise AssertionError(vector["name"])


def test_consumer_proposal_agreement_is_digest_only_and_non_authorizing() -> None:
    agreement = json.loads(
        (CONTRACT / "consumer-proposal-agreement.json").read_text(encoding="utf-8")
    )
    assert len(agreement["consumer_proposals"]) == 6
    assert all(
        len(digest) == 64 for digest in agreement["consumer_proposals"].values()
    )
    assert agreement["kernel_change_required"] is False
    assert agreement["engine_route_enabled"] is False
    assert agreement["engine_implementation_authorized"] is False


def test_authoritative_draft_manifest_matches_schema_bytes() -> None:
    manifest = json.loads(
        (CONTRACT / "authoritative-draft-manifest.json").read_text(encoding="utf-8")
    )
    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(SCHEMAS.glob("*.json"))
    }
    assert manifest["schemas"] == actual
    evidence = {
        path: hashlib.sha256((CONTRACT / path).read_bytes()).hexdigest()
        for path in manifest["evidence"]
    }
    assert manifest["evidence"] == evidence
    assert manifest["status"] == "claim_source_erratum_candidate_implementation_paused"
    assert manifest["verification"]["production_implementation_authorized"] is False
    assert manifest["published_contracts_modified"] is False
    assert manifest["runtime_route_enabled"] is False


def test_trusted_activation_requests_and_authority_echo() -> None:
    mapping = json.loads((CONTRACT / "route-mapping.json").read_text(encoding="utf-8"))
    assert mapping["claim_activation_authority"] == {
        "principal_source": "authenticated_transport",
        "required_capability": "runtime_workflow:activate",
        "request_body_principal_authoritative": False,
        "worker_pull_authoritative": False,
    }
    cases = (
        ("provider-activation.valid.json", "pdx_runtime_provider_claim_request_v2.schema.json", "pdx_runtime_provider_claim_v1.schema.json"),
        ("check-activation.valid.json", "pdx_runtime_check_claim_request_v2.schema.json", "pdx_runtime_check_claim_v1.schema.json"),
    )
    for fixture_name, request_schema, response_schema in cases:
        fixture = _read("examples", fixture_name)
        assert _errors(request_schema, fixture["request"]) == []
        assert _errors(response_schema, fixture["response"]) == []
        for field in ("workflow_step_id", "execution_constraints_digest", "idempotency_key", "workspace_ref"):
            assert fixture["request"][field] == fixture["response"][field]
    provider = _read("examples", "provider-activation.valid.json")
    for field in ("invocation_id", "provider_id", "provider_instance_id"):
        assert provider["request"][field] == provider["response"][field]
    plan = _read("examples", "workflow-plan.valid.json")
    assert provider["response"]["operation_digest"] == plan["steps"][0]["operation_digest"]
    check = _read("examples", "check-activation.valid.json")
    assert check["response"]["check_definition_digest"] == plan["steps"][1]["check_definition_digest"]


def test_activation_rejections_are_atomic_and_check_cannot_select_provider() -> None:
    semantics = _semantic_module()
    plan = _read("examples", "workflow-plan.valid.json")
    provider = _read("examples", "provider-activation.valid.json")["request"]
    check = _read("examples", "check-activation.valid.json")["request"]
    polluted_check = {**check, "provider_id": "generic.cli"}
    assert _errors("pdx_runtime_check_claim_request_v2.schema.json", polluted_check)

    baseline = {"provider_attempts": 0, "check_attempts": 0}
    instance_id = provider["control_plane_instance_id"]
    rejected = (
        semantics.validate_activation(plan, "running", provider, "provider", authenticated=False),
        semantics.validate_activation(plan, "running", provider, "provider", authenticated=True, authorized=False, authenticated_instance_id=instance_id),
        semantics.validate_activation(plan, "failed", provider, "provider", authenticated=True, authenticated_instance_id=instance_id),
        semantics.validate_activation(plan, "running", provider, "provider", authenticated=True, authenticated_instance_id=instance_id, step_state="running"),
        semantics.validate_activation(plan, "running", provider, "check", authenticated=True, authenticated_instance_id=instance_id),
        semantics.validate_activation(plan, "running", provider, "provider", authenticated=True, authenticated_instance_id="other_control_001"),
    )
    assert rejected == (
        ["ACTIVATION_AUTH_REQUIRED"], ["ACTIVATION_AUTH_FORBIDDEN"],
        ["WORKFLOW_NOT_ACTIVE"], ["STEP_NOT_READY"], ["STEP_KIND_MISMATCH"],
        ["ACTIVATION_PRINCIPAL_MISMATCH"],
    )
    assert baseline == {"provider_attempts": 0, "check_attempts": 0}


def test_activation_idempotency_binding_and_concurrent_token_recovery() -> None:
    semantics = _semantic_module()
    plan = _read("examples", "workflow-plan.valid.json")
    request = _read("examples", "provider-activation.valid.json")["request"]
    counters = {"provider_attempts": 0, "check_attempts": 0}
    secret = b"contract-evidence-server-secret"
    first = semantics.activation_transition(
        counters, None, request, "provider", server_secret=secret,
        claim_id="claim_provider_001",
    )
    existing = {
        "kind": "provider", "binding": first["binding"], "attempt_number": 1,
        "invocation_id": request["invocation_id"],
        "lease_token_digest": first["lease_token_digest"],
    }
    auth = {"authenticated": True, "authenticated_instance_id": request["control_plane_instance_id"]}
    assert semantics.validate_activation(
        plan, "running", request, "provider", existing=existing, **auth
    ) == []
    retry_a = semantics.activation_transition(
        first["counters"], existing, request, "provider", server_secret=secret,
        claim_id="claim_provider_001",
    )
    retry_b = semantics.activation_transition(
        first["counters"], existing, request, "provider", server_secret=secret,
        claim_id="claim_provider_001",
    )
    assert retry_a == retry_b
    assert retry_a["lease_token"] == first["lease_token"]
    assert retry_a["lease_token_digest"] == first["lease_token_digest"]
    assert retry_a["counters"]["provider_attempts"] == 1
    assert retry_a["attempt_number"] == 1

    for field, value in (
        ("workflow_step_id", "step_reviewer"), ("provider_id", "other.provider"),
        ("provider_instance_id", "provider_instance_002"),
        ("control_plane_instance_id", "hub_control_002"),
        ("correlation_id", "correlation_002"),
        ("lease_seconds", 120),
        ("workspace_ref", "workspace://root/other"),
        ("execution_constraints_digest", "f" * 64),
    ):
        changed = {**request, field: value}
        assert semantics.validate_activation(
            plan, "running", changed, "provider", existing=existing,
            authenticated=True, authenticated_instance_id=changed["control_plane_instance_id"],
        ) == ["ACTIVATION_BINDING_CONFLICT"]

    new_request_id = {**request, "request_id": "request_provider_002"}
    assert semantics.activation_binding(new_request_id, "provider") == first["binding"]
