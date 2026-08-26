"""Phase 0 Engine contracts: private job interface, staging, Kernel identity profile."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from pdx_artifact_core import RunState, validate_artifact_storage_identity

ROOT = Path(__file__).resolve().parents[1]
PHASE0 = ROOT / "docs" / "phase0"
MANIFEST_NAME = "fixture-digest-manifest.json"
FROZEN = {
    "pdx_prodocux_compatibility_v1.json": (
        "0b860fc0a5693a96083de1560ff030398e762c9f0c9dc4c0975eceb1d6ca1303"
    ),
    "pdx_prodocux_compatibility_v2.json": (
        "c301aba7442b150b8186ce3b7cd8da99e9470ad0592c13f7f2818d38fd5f378e"
    ),
    "pdx_prodocux_compatibility_v3.json": (
        "9591ab363472db78efb64265e3050fa4626be43783f848d0888e732898486d2b"
    ),
}
FORBIDDEN = ("wordpress", "woocommerce", "farpals", "oauth")

EXAMPLE_SCHEMA = {
    "job_create.intake_document.json": "pdx_internal_job_create_v1.schema.json",
    "job_create.idempotency_conflict.json": "pdx_internal_job_create_v1.schema.json",
    "job_status.pending.json": "pdx_internal_job_status_v1.schema.json",
    "job_status.cancelled.json": "pdx_internal_job_status_v1.schema.json",
    "job_cancel.request.json": "pdx_internal_job_cancel_v1.schema.json",
    "job_reconcile.request.json": "pdx_internal_job_reconcile_v1.schema.json",
    "job_error.digest_conflict.json": "pdx_internal_error_v1.schema.json",
    "staging_handle.ok.json": "pdx_staging_handle_v1.schema.json",
    "artifact_identity.artifact_uri.json": (
        "pdx_prodocux_artifact_identity_profile_v1.schema.json"
    ),
}

NEGATIVE_SCHEMA = {
    "job_create.application_subject_type.json": "pdx_internal_job_create_v1.schema.json",
    "job_status.queued_state.json": "pdx_internal_job_status_v1.schema.json",
    "job_status.persisted_payload.json": "pdx_internal_job_status_v1.schema.json",
    "artifact_identity.gs_uri.json": (
        "pdx_prodocux_artifact_identity_profile_v1.schema.json"
    ),
    "artifact_identity.local_path.json": (
        "pdx_prodocux_artifact_identity_profile_v1.schema.json"
    ),
}


def _schema(name: str) -> dict:
    return json.loads((PHASE0 / "schemas" / name).read_text(encoding="utf-8"))


def _validate(schema: dict, instance: dict) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [err.message for err in validator.iter_errors(instance)]


def _digest_files() -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(PHASE0.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(PHASE0).as_posix()
        if rel in {MANIFEST_NAME, "README.md"}:
            continue
        if path.suffix not in {".json"}:
            continue
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def test_frozen_compatibility_bytes_are_unchanged() -> None:
    for name, digest in FROZEN.items():
        path = ROOT / "compatibility" / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_phase0_not_packaged_as_core_contract() -> None:
    packaged = ROOT / "packages" / "pdx_artifact_core" / "src" / "pdx_artifact_core" / "schemas"
    assert packaged.is_dir()
    phase0_names = {path.name for path in (PHASE0 / "schemas").glob("*.json")}
    packaged_names = {path.name for path in packaged.glob("*.json")}
    assert phase0_names.isdisjoint(packaged_names)


def test_phase0_examples_and_bridge_fixtures_validate() -> None:
    for example_name, schema_name in EXAMPLE_SCHEMA.items():
        instance = json.loads(
            (PHASE0 / "examples" / example_name).read_text(encoding="utf-8")
        )
        assert _validate(_schema(schema_name), instance) == [], example_name
    bridge_schema = _schema("pdx_engine_kernel_bridge_v1.schema.json")
    for path in (PHASE0 / "fixtures").glob("bridge.*.json"):
        instance = json.loads(path.read_text(encoding="utf-8"))
        assert _validate(bridge_schema, instance) == [], path.name
    mapping = json.loads((PHASE0 / "e05-route-mapping.json").read_text(encoding="utf-8"))
    assert _validate(_schema("pdx_phase0_e05_route_mapping_v1.schema.json"), mapping) == []


def test_e05_cancel_and_reconcile_examples_are_requests() -> None:
    cancel = json.loads(
        (PHASE0 / "examples" / "job_cancel.request.json").read_text(encoding="utf-8")
    )
    reconcile = json.loads(
        (PHASE0 / "examples" / "job_reconcile.request.json").read_text(encoding="utf-8")
    )
    cancelled = json.loads(
        (PHASE0 / "examples" / "job_status.cancelled.json").read_text(encoding="utf-8")
    )
    assert cancel["schema_version"] == "pdx_internal_job_cancel_v1"
    assert reconcile["schema_version"] == "pdx_internal_job_reconcile_v1"
    assert cancelled["schema_version"] == "pdx_internal_job_status_v1"
    assert cancelled["state"] == "cancelled"


def test_phase0_negatives_fail() -> None:
    for negative_name, schema_name in NEGATIVE_SCHEMA.items():
        instance = json.loads(
            (PHASE0 / "negative" / negative_name).read_text(encoding="utf-8")
        )
        assert _validate(_schema(schema_name), instance), negative_name


def test_status_example_omits_payload_bytes() -> None:
    status = json.loads(
        (PHASE0 / "examples" / "job_status.pending.json").read_text(encoding="utf-8")
    )
    dumped = json.dumps(status)
    assert "content_b64" not in dumped
    assert "YQ==" not in dumped
    assert status["state"] == "pending"
    assert "queued" not in dumped


def test_same_idempotency_key_different_operation_digest_is_conflict_pair() -> None:
    first = json.loads(
        (PHASE0 / "examples" / "job_create.intake_document.json").read_text(
            encoding="utf-8"
        )
    )
    second = json.loads(
        (PHASE0 / "examples" / "job_create.idempotency_conflict.json").read_text(
            encoding="utf-8"
        )
    )
    assert first["idempotency_key"] == second["idempotency_key"]
    assert first["operation_digest"] != second["operation_digest"]


def test_runstate_matches_phase0_limits() -> None:
    limits = json.loads((PHASE0 / "limits.json").read_text(encoding="utf-8"))
    assert set(limits["run_states"]) == {state.value for state in RunState}
    assert limits["max_decoded_bytes"] == 33554432
    assert limits["staging_ttl_seconds_default"] == 3600
    assert limits["host_consumer_may_apply_stricter_ceilings"] is True


def test_generic_core_identity_still_allows_gs_but_profile_does_not() -> None:
    generic = {
        "artifact_id": "artifact-example-1",
        "uri": "gs://bucket/summary.pdf",
        "sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
        "size_bytes": 128,
        "media_type": "application/pdf",
        "created_at": "2026-08-26T12:00:00Z",
    }
    assert validate_artifact_storage_identity(generic) == []
    profile = {
        "schema_version": "pdx_prodocux_artifact_identity_profile_v1",
        **{k: v for k, v in generic.items() if k != "created_at"},
        "created_at": generic["created_at"],
    }
    assert _validate(
        _schema("pdx_prodocux_artifact_identity_profile_v1.schema.json"),
        profile,
    )


def test_phase0_schemas_examples_and_fixtures_omit_application_host_types() -> None:
    for folder in ("schemas", "examples", "fixtures"):
        for path in (PHASE0 / folder).glob("*.json"):
            text = path.read_text(encoding="utf-8").casefold()
            for token in FORBIDDEN:
                assert token not in text, f"{path} contains {token}"
    mapping = (PHASE0 / "e05-route-mapping.json").read_text(encoding="utf-8").casefold()
    for token in FORBIDDEN:
        assert token not in mapping


def test_fixture_digest_manifest_matches_hashed_files() -> None:
    computed = _digest_files()
    manifest = json.loads((PHASE0 / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "pdx_phase0_fixture_digest_manifest_v1"
    assert manifest["algorithm"] == "sha256"
    assert manifest["canonicalization"] == (
        "raw UTF-8 file bytes as stored; JSON uses LF; no JSON re-encoding"
    )
    assert manifest["root"] == "docs/phase0"
    assert MANIFEST_NAME not in manifest["files"]
    assert manifest["files"] == computed
