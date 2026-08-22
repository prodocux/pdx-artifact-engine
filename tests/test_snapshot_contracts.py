from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from pdx_artifact_core import (
    CheckpointRepository,
    DecisionRepository,
    validate_run_snapshot,
)
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = (
    ROOT
    / "packages"
    / "pdx_artifact_core"
    / "src"
    / "pdx_artifact_core"
    / "schemas"
)
EXAMPLES = ROOT / "examples" / "contracts"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry() -> Registry:
    registry = Registry()
    for name in (
        "artifact_storage_identity.v1.schema.json",
        "workflow_checkpoint.v1.schema.json",
        "step_receipt.v1.schema.json",
    ):
        schema = _load(SCHEMAS / name)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


def test_snapshot_schemas_are_valid_draft_2020_12() -> None:
    for name in ("step_receipt.v1.schema.json", "run_snapshot.v1.schema.json"):
        Draft202012Validator.check_schema(_load(SCHEMAS / name))


def test_step_receipt_example_matches_contract() -> None:
    schema = _load(SCHEMAS / "step_receipt.v1.schema.json")
    Draft202012Validator(schema, registry=_registry()).validate(
        _load(EXAMPLES / "step_receipt_v1.json")
    )


def test_run_snapshot_example_matches_contract() -> None:
    value = _load(EXAMPLES / "run_snapshot_v1.json")
    schema = _load(SCHEMAS / "run_snapshot.v1.schema.json")
    Draft202012Validator(schema, registry=_registry()).validate(
        value
    )
    assert validate_run_snapshot(value) == []


def test_unknown_outcome_requires_reconciliation() -> None:
    schema = _load(SCHEMAS / "step_receipt.v1.schema.json")
    value = _load(EXAMPLES / "step_receipt_v1.json")
    value["status"] = "unknown_outcome"
    value.pop("output_digest")
    value["error"] = {
        "code": "OUTCOME_UNKNOWN",
        "message": "The host must reconcile before retry.",
        "retryable": False,
        "reconcile_required": False,
    }
    errors = list(Draft202012Validator(schema, registry=_registry()).iter_errors(value))
    assert errors


def test_repository_protocols_are_runtime_checkable() -> None:
    class SnapshotStore:
        def put_if_absent(self, snapshot):
            return True

        def get(self, snapshot_id):
            return None

        def compare_and_set(self, snapshot_id, expected_version, snapshot):
            return True

    class DecisionStore:
        def record_once(self, decision):
            return decision

        def get_by_checkpoint_id(self, checkpoint_id):
            return None

        def get_by_idempotency_key(self, key):
            return None

    assert isinstance(SnapshotStore(), CheckpointRepository)
    assert isinstance(DecisionStore(), DecisionRepository)


def test_snapshot_contracts_contain_no_domain_or_host_ownership_fields() -> None:
    forbidden = (
        "commerce_listing",
        "provider_poll_interval",
        "regulatory_conclusion",
        "tenant_id",
    )
    for name in ("step_receipt.v1.schema.json", "run_snapshot.v1.schema.json"):
        text = (SCHEMAS / name).read_text(encoding="utf-8").casefold()
        assert not any(term in text for term in forbidden), name
