"""Published Engine a5 evidence; historical release records remain immutable."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "compatibility" / "pdx_artifact_engine_release_a5.json"


def test_published_a5_exact_source_and_asset_hashes() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert record["status"] == "published"
    assert record["version"] == "0.3.0a5"
    assert record["tag"] == "v0.3.0a5"
    assert record["release_commit"] == "49c53ac674dbcfda7735f022ff3f38a07b8090f2"
    assert record["files"] == {
        "pdx_artifact_engine-0.3.0a5-py3-none-any.whl":
            "75e7a180d0f7f4638e276612a336e26d0595aa15092a8ab538a0af68276d4854",
        "pdx_artifact_engine-0.3.0a5.tar.gz":
            "5bcb63b281893dae11abbd7fa219dc4f162cf4e33aa2baa4809f695d00d21bca",
    }


def test_published_a5_preserves_release_boundaries() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert record["contract_provenance"]["packaged_schema_count"] == 23
    assert "Farpals-owned" in record["qualification"]["formal_pin_promotion"]
    assert "0.2.0a2" in record["verification"]["media"]
    assert "skipped" in record["verification"]["github_actions"]
