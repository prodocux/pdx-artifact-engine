"""Published Engine a6 evidence; a5 release and frozen contracts stay immutable."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "compatibility" / "pdx_artifact_engine_release_a6.json"
PROJECTION_SCHEMA = (
    ROOT
    / "runtime"
    / "pdx_artifact_engine"
    / "contracts"
    / "runtime_provider_workflow"
    / "pdx_runtime_provider_step_projection_v1.schema.json"
)


def test_published_a6_exact_source_assets_and_additive_schema() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert record["status"] == "published"
    assert record["version"] == "0.3.0a6"
    assert record["tag"] == "v0.3.0a6"
    assert record["release_commit"] == "1f29a792b9b86cef1c54706ab154ad4c50cbfc6a"
    assert record["files"] == {
        "pdx_artifact_engine-0.3.0a6-py3-none-any.whl":
            "6956d16c15126835528094a944c03f283cb2182c2cec2c8d0a1ba7dc8a9f13fa",
        "pdx_artifact_engine-0.3.0a6.tar.gz":
            "68afb9d5d698aa40f0a8ca2f6d2d5532e83373d1e8c04175272a9998a096e59c",
    }
    assert record["additive_contract"]["schema_sha256"] == hashlib.sha256(
        PROJECTION_SCHEMA.read_bytes()
    ).hexdigest()


def test_published_a6_preserves_boundaries() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert record["additive_contract"]["a5_frozen_schemas_modified"] is False
    assert "Farpals-owned" in record["qualification"]["formal_pin_promotion"]
    assert "0.2.0a2" in record["verification"]["media"]
    assert "skipped" in record["verification"]["github_actions"]
