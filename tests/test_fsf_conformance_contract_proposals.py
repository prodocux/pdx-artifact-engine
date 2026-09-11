from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "adapters" / "media" / "pdx_adapter_media" / "schemas"
ENGINE = ROOT / "docs" / "conformance-checks" / "schemas"
COMMON = ROOT / "runtime" / "pdx_artifact_engine" / "contracts" / "runtime_provider_workflow" / "pdx_runtime_provider_common_v1.schema.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry(folder: Path) -> Registry:
    registry = Registry()
    for path in folder.glob("*.json"):
        schema = _load(path)
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(path.name, resource)
        registry = registry.with_resource(schema["$id"], resource)
    return registry


def test_media_proposal_compiles_and_keeps_not_evaluated_out_of_runstate() -> None:
    schemas = [_load(path) for path in MEDIA.glob("*.json")]
    assert len(schemas) == 3
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    result = next(s for s in schemas if s["$id"].endswith("conformance-result-v1.json"))
    assert result["properties"]["evaluation_status"]["enum"] == ["conforms", "does_not_conform", "evaluation_failed", "not_evaluated"]
    workflow_state = _load(ROOT / "runtime" / "pdx_artifact_engine" / "contracts" / "runtime_provider_workflow" / "pdx_runtime_provider_workflow_state_v1.schema.json")
    assert "not_evaluated" not in json.dumps(workflow_state)


def test_media_request_accepts_fsf_expected_and_rejects_empty_expected() -> None:
    profile = {
        "schema_version": "pdx_media_technical_profile_v2",
        "identity": {"name": "shot.mp4", "extension": ".mp4", "size_bytes": 42, "sha256": "a" * 64, "media_type": "video/mp4"},
        "probe_status": "measured", "container": "mov,mp4", "duration_seconds": 5.0,
        "streams": [{"index": 0, "kind": "video", "codec": "h264", "width": 1024, "height": 576, "fps": 24}],
        "interpretation": "none",
    }
    request_schema = _load(MEDIA / "pdx_media_conformance_request_v1.json")
    validator = Draft202012Validator(request_schema, registry=_registry(MEDIA))
    base = {"schema_version": "pdx_media_conformance_request_v1", "request_id": "request:media:001", "profile": profile}
    assert not list(validator.iter_errors({**base, "expected": {"width": 1024, "height": 576, "fps": 24, "duration_seconds": 5, "duration_tolerance_seconds": 0.25, "audio": "forbidden"}}))
    assert list(validator.iter_errors({**base, "expected": {}}))

    fixture = _load(ROOT / "adapters" / "media" / "examples" / "fsf_broll_expected.v1.json")
    assert fixture["source"] == "b-roll-library-generator output contract and recipe"
    assert not list(validator.iter_errors({**base, "expected": fixture["expected"]}))


def test_media_result_separates_not_requested_unavailable_and_mismatch() -> None:
    schema = _load(MEDIA / "pdx_media_conformance_result_v1.json")
    validator = Draft202012Validator(schema)
    base = {"schema_version": "pdx_media_conformance_result_v1", "profile_digest": "a" * 64, "interpretation": "none"}
    assert not list(validator.iter_errors({**base, "evaluation_status": "not_evaluated", "issues": []}))
    evaluated = {**base, "request_id": "request:media:001", "expected_digest": "b" * 64}
    unavailable = {**evaluated, "evaluation_status": "evaluation_failed", "issues": [{"code": "MEDIA_ANALYZER_UNAVAILABLE", "location": "analyzer", "message": "ffprobe unavailable", "retryable": True}]}
    mismatch = {**evaluated, "evaluation_status": "does_not_conform", "issues": [{"code": "MEDIA_DURATION_MISMATCH", "location": "duration_seconds", "message": "outside tolerance", "retryable": False}]}
    assert not list(validator.iter_errors(unavailable))
    assert not list(validator.iter_errors(mismatch))
    assert list(validator.iter_errors({**unavailable, "evaluation_status": "not_evaluated"}))


def test_engine_binding_is_generic_and_digest_bound() -> None:
    path = ENGINE / "pdx_conformance_check_binding_v1.schema.json"
    schema = _load(path)
    Draft202012Validator.check_schema(schema)
    value = {
        "schema_version": "pdx_conformance_check_binding_v1", "check_schema_id": "https://prodocux.dev/schemas/pdx/media/conformance-request-v1.json",
        "payload_digest": "a" * 64, "report_schema_id": "https://prodocux.dev/schemas/pdx/media/conformance-result-v1.json", "report_digest": "b" * 64,
        "report_artifact": {"schema_version": "prodocux_opaque_artifact_v1", "artifact_id": "artifact:report:001", "uri": "artifact://reports/media-001.json", "sha256": "c" * 64, "size_bytes": 321, "media_type": "application/json"},
        "execution_result": "succeeded",
    }
    common = _load(COMMON)
    registry = Registry().with_resource(common["$id"], Resource.from_contents(common))
    assert not list(Draft202012Validator(schema, registry=registry).iter_errors(value))
    encoded = json.dumps(schema).lower()
    assert "template-conformance" not in encoded
    assert "/media/conformance" not in encoded

    unsafe = {**value, "report_artifact": {**value["report_artifact"], "uri": "artifact://reports/../secret"}}
    assert list(Draft202012Validator(schema, registry=registry).iter_errors(unsafe))


def test_fsf_consumer_mapping_preserves_successful_nonconformance_report() -> None:
    mapping = _load(ROOT / "docs" / "conformance-checks" / "examples" / "fsf-consumer-mapping.v1.json")
    cases = {item["evaluation_status"]: item for item in mapping["cases"]}
    assert cases["not_evaluated"]["create_binding"] is False
    assert cases["not_evaluated"]["check_terminal_outcome"] is None
    assert cases["evaluation_failed"]["check_terminal_outcome"] == "failed"
    assert cases["does_not_conform"]["check_terminal_outcome"] == "succeeded"
    assert cases["does_not_conform"]["host_action"] == "block_next_product_step"
    assert cases["conforms"]["check_terminal_outcome"] == "succeeded"
    assert mapping["completed_with_review_allowed"] is False


def test_manifest_locks_owned_schema_bytes_without_authorizing_runtime() -> None:
    manifest = _load(ROOT / "docs" / "conformance-checks" / "proposal-manifest.v1.json")
    assert manifest["status"] == "frozen_bilateral_contract"
    assert manifest["implementation_authorized"] is False
    paths = {
        **{path.name: path for path in MEDIA.glob("*.json")},
        **{path.name: path for path in ENGINE.glob("*.json")},
    }
    assert manifest["schemas"] == {
        name: hashlib.sha256(paths[name].read_bytes()).hexdigest()
        for name in manifest["schemas"]
    }
    evidence_paths = {
        "fsf_broll_expected.v1.json": ROOT / "adapters" / "media" / "examples" / "fsf_broll_expected.v1.json",
        "fsf-consumer-mapping.v1.json": ROOT / "docs" / "conformance-checks" / "examples" / "fsf-consumer-mapping.v1.json",
    }
    assert manifest["evidence"] == {
        name: hashlib.sha256(evidence_paths[name].read_bytes()).hexdigest()
        for name in manifest["evidence"]
    }
    assert set(manifest["ownership"].values()) == {"media_package", "engine"}
