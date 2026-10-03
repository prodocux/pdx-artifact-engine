"""Negotiation tests for the ER-002 governed dynamic-dispatch draft.

These tests validate docs-only proposal contracts. Passing them does not freeze
the schemas or authorize runtime implementation.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "docs" / "dynamic-dispatch"
SCHEMAS = DRAFT / "schemas"
EXAMPLES = DRAFT / "examples"
RUNTIME_COMMON = (
    ROOT
    / "docs"
    / "runtime-provider-workflow"
    / "schemas"
    / "pdx_runtime_provider_common_v1.schema.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _schemas() -> list[dict]:
    return [_load(path) for path in sorted(SCHEMAS.glob("*.json"))]


def _registry() -> Registry:
    registry = Registry()
    for schema in [*_schemas(), _load(RUNTIME_COMMON)]:
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


def _schema_for_version(version: str) -> dict:
    for schema in _schemas():
        const = schema.get("properties", {}).get("schema_version", {}).get("const")
        if const == version:
            return schema
    raise AssertionError(f"no draft schema for {version}")


def _errors(schema: dict, value: dict) -> list:
    return list(
        Draft202012Validator(
            schema, registry=_registry(), format_checker=FormatChecker()
        ).iter_errors(value)
    )


def test_draft_schemas_are_valid_draft_2020_12() -> None:
    schemas = _schemas()
    assert len(schemas) == 14
    for schema in schemas:
        Draft202012Validator.check_schema(schema)


def test_all_examples_validate() -> None:
    for path in sorted(EXAMPLES.glob("*.json")):
        value = _load(path)
        schema = _schema_for_version(value["schema_version"])
        assert not _errors(schema, value), path.name

    route = _load(DRAFT / "route-mapping.json")
    schema = _schema_for_version(route["schema_version"])
    assert not _errors(schema, route)


def test_activation_request_cannot_carry_proposal_or_allowlist() -> None:
    value = _load(EXAMPLES / "activation-request.valid.json")
    schema = _schema_for_version(value["schema_version"])
    value["arguments"] = {"expression": "1+1"}
    value["allowed_tools"] = ["calc"]
    assert _errors(schema, value)


def test_policy_registration_cannot_claim_engine_derived_authority() -> None:
    value = _load(EXAMPLES / "policy-register.valid.json")
    schema = _schema_for_version(value["schema_version"])
    value["registered_at"] = "2026-10-03T12:00:00Z"
    value["policy_digest"] = "0" * 64
    value["policy_status"] = "active"
    assert _errors(schema, value)


def test_rejected_receipt_cannot_claim_run_or_cas_publication() -> None:
    value = _load(EXAMPLES / "receipt-rejected.valid.json")
    schema = _schema_for_version(value["schema_version"])
    value["run_b_id"] = "run_forged_001"
    value["receipt_cas_published"] = True
    assert _errors(schema, value)


def test_completed_receipt_requires_verified_published_output() -> None:
    value = _load(EXAMPLES / "receipt-completed.valid.json")
    schema = _schema_for_version(value["schema_version"])
    value["output_schema_verified"] = False
    value["executor_output_artifacts_published"] = False
    assert _errors(schema, value)


def test_external_decision_artifact_uses_existing_safe_opaque_uri() -> None:
    receipt = _load(EXAMPLES / "decision-receipt.valid.json")
    receipt["source_manifest_artifact"]["uri"] = "artifact://dispatch/../escape.json"
    schema = _schema_for_version(receipt["schema_version"])
    assert _errors(schema, receipt)


def test_route_operations_are_complete_and_unique() -> None:
    route = _load(DRAFT / "route-mapping.json")
    operations = [item["operation"] for item in route["routes"]]
    assert len(operations) == len(set(operations)) == 7
    assert set(operations) == {
        "register_policy",
        "revoke_policy",
        "import_external_decision_receipt",
        "activate",
        "get_step_projection",
        "get_dispatch_receipt",
        "reconcile_dispatch",
    }


def test_same_job_decision_is_engine_recorded_not_imported_by_caller() -> None:
    mapping = _load(DRAFT / "route-mapping.json")
    imports = [
        item for item in mapping["routes"]
        if item["operation"] == "import_external_decision_receipt"
    ]
    assert len(imports) == 1
    assert "external" in imports[0]["operation"]


def _ecmascript_number(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("non-finite")
    if value == 0:
        return "0"
    rendered = repr(value).lower()
    if "e" in rendered:
        mantissa, exponent = rendered.split("e")
        exponent_value = int(exponent)
        if -6 <= exponent_value < 21:
            rendered = format(value, ".15f").rstrip("0").rstrip(".")
        else:
            rendered = f"{mantissa}e{exponent_value:+d}"
    elif rendered.endswith(".0"):
        rendered = rendered[:-2]
    return rendered


def _python_jcs(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return _ecmascript_number(value)
    if isinstance(value, str):
        value.encode("utf-8", "strict")
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(_python_jcs(item) for item in value) + "]"
    assert isinstance(value, dict)
    ordered = sorted(value, key=lambda key: key.encode("utf-16-be"))
    return "{" + ",".join(
        f"{json.dumps(key, ensure_ascii=False)}:{_python_jcs(value[key])}"
        for key in ordered
    ) + "}"


def test_rfc8785_vectors_have_python_node_parity() -> None:
    vectors = _load(DRAFT / "canonicalization-vectors.v1.json")
    for vector in vectors["positive"]:
        canonical = _python_jcs(vector["input"])
        assert canonical == vector["canonical"], vector["name"]
        assert hashlib.sha256(canonical.encode()).hexdigest() == vector["sha256"]

    completed = subprocess.run(
        ["node", str(DRAFT / "semantic-validator.mjs")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "DYNAMIC_DISPATCH_SEMANTICS_PASS 3+2" in completed.stdout


def test_semantic_validator_rejects_mutated_authority_and_bounds() -> None:
    program = """
import fs from 'node:fs';
import {validatePolicy, validateArguments, validateTerminalReceipt} from './docs/dynamic-dispatch/semantic-validator.mjs';
const load = (name) => JSON.parse(fs.readFileSync(`./docs/dynamic-dispatch/examples/${name}`, 'utf8'));
const expect = (fn, code) => { try { fn(); throw new Error(`accepted ${code}`); } catch (error) { if (error.code !== code) throw error; } };
const policy = load('policy.valid.json');
policy.allowed_tool_names_digest = '0'.repeat(64);
expect(() => validatePolicy(policy), 'DISPATCH_ALLOWED_TOOLS_DIGEST_INVALID');
const limits = {max_depth: 8, max_properties_per_object: 64, max_total_keys: 256, max_canonical_bytes: 65536, max_secret_refs: 8, max_array_length: 1024};
expect(() => validateArguments({items: Array(1025).fill(0)}, limits), 'DISPATCH_PROPOSAL_BOUNDS_EXCEEDED');
const receipt = load('receipt-rejected.valid.json');
receipt.run_b_id = 'run_forged_001';
expect(() => validateTerminalReceipt(receipt), 'DISPATCH_RECEIPT_TERMINAL_INVALID');
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_negotiation_manifest_matches_draft_bytes() -> None:
    manifest = _load(DRAFT / "draft-manifest.json")
    assert manifest["status"] == "bilateral_negotiation_draft"
    assert manifest["freeze_authorized"] is False
    assert manifest["implementation_authorized"] is False
    assert manifest["release_version"] is None
    assert manifest["schema_count"] == len(_schemas()) == 14
    for relative, expected in manifest["files"].items():
        actual = hashlib.sha256((DRAFT / relative).read_bytes()).hexdigest()
        assert actual == expected, relative


def test_contract_freeze_locks_reviewed_authority_bytes() -> None:
    freeze = _load(DRAFT / "contract-freeze.v1.json")
    assert freeze["status"] == "frozen"
    assert freeze["implementation_authorized"] is False
    assert freeze["release_version"] is None
    pre_freeze = freeze["pre_freeze_manifest"]
    assert hashlib.sha256((DRAFT / pre_freeze["path"]).read_bytes()).hexdigest() == pre_freeze["sha256"]

    for filename, expected in freeze["schemas"].items():
        assert hashlib.sha256((SCHEMAS / filename).read_bytes()).hexdigest() == expected
    for filename, expected in freeze["authority"].items():
        assert hashlib.sha256((DRAFT / filename).read_bytes()).hexdigest() == expected
    for filename, expected in freeze["examples"].items():
        assert hashlib.sha256((EXAMPLES / filename).read_bytes()).hexdigest() == expected
