"""Published rc4/a4 evidence; never update historical release records in place."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "compatibility" / "pdx_prodocux_release_rc4_a4.json"
EXPECTED = {
    "prodocux": {
        "version": "0.3.0rc4",
        "release_commit": "44e29bd64089279910f4d78a0a36cf3fdb953cc7",
        "files": {
            "prodocux-0.3.0rc4-py3-none-any.whl": "6c6801318f4b649877ca680d4897bbe6917def60f888073ec6d5e20f916c3d47",
            "prodocux-0.3.0rc4.tar.gz": "d3fa8b2c04f1a51f620d50ea01d23885d844baba7dc8ec41dc8ea14e85919ea1",
        },
    },
    "pdx_artifact_engine": {
        "version": "0.3.0a4",
        "release_commit": "2acdebf73134ed106a636ed38e1ecce6596eb751",
        "files": {
            "pdx_artifact_engine-0.3.0a4-py3-none-any.whl": "0435fbb2e362e18c34bcad1d955893b07dac353de3f9bd6f5de0c3fd76c6d005",
            "pdx_artifact_engine-0.3.0a4.tar.gz": "90408e8e0319b1aa5c5d0269b67dae6dd92ec44916c060b48eb1d97f9cc049a3",
        },
    },
}


def test_published_rc4_a4_exact_source_pins_and_asset_hashes() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert record["schema_version"] == "pdx_prodocux_release_overlay_v1"
    assert record["status"] == "published"
    assert record["supersedes"]["record"] == "pdx_prodocux_release_rc3_a3.json"
    for component, expected in EXPECTED.items():
        for field, value in expected.items():
            assert record[component][field] == value
        assert record[component]["tag"] == "v" + expected["version"]
    assert record["pdx_adapter_media"]["version"] == "0.2.0a2"
    assert "skipped" in record["pdx_adapter_media"]["note"]
    manifest = ROOT / "compatibility" / record["compatibility"]["manifest"]
    assert (
        record["compatibility"]["sha256"]
        == hashlib.sha256(manifest.read_bytes()).hexdigest()
    )


def test_rc4_a4_overlay_preserves_security_scope() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert "not zero OS advisories" in record["security_boundary"]["os_acceptance"]
    assert "Farpals-owned" in record["security_boundary"]["farpals"]
    assert "not independent Sigstore" in record["verification"]["provenance"]


def test_rc4_a4_overlay_matches_sibling_when_present() -> None:
    sibling_name = "pdx-artifact-engine" if ROOT.name == "prodocux" else "prodocux"
    sibling = ROOT.parent / sibling_name / "compatibility" / RECORD.name
    if sibling.exists():
        assert RECORD.read_bytes() == sibling.read_bytes()
