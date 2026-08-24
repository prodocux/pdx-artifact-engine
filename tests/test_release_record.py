"""Verify the current publication record without mutating frozen manifests."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_RECORD = ROOT / "compatibility" / "pdx_prodocux_release_v1.json"
V3_MANIFEST = ROOT / "compatibility" / "pdx_prodocux_compatibility_v3.json"
SIBLING = (
    ROOT.parent / "pdx-artifact-engine"
    if ROOT.name == "prodocux"
    else ROOT.parent / "prodocux"
)


def test_current_release_record_matches_frozen_v3_and_public_pins() -> None:
    record = json.loads(RELEASE_RECORD.read_text(encoding="utf-8"))
    assert record["schema_version"] == "pdx_prodocux_release_v1"
    assert record["status"] == "published"
    assert record["compatibility"]["sha256"] == hashlib.sha256(
        V3_MANIFEST.read_bytes()
    ).hexdigest()
    assert "historical evidence" in record["compatibility"][
        "publication_gate_interpretation"
    ]

    assert record["prodocux"]["version"] == "0.3.0rc2"
    assert record["prodocux"]["release_commit"] == (
        "ca165e98f3aef1c0449ebc0f5bc47ea4ebe1f5b0"
    )
    assert record["pdx_artifact_engine"]["version"] == "0.3.0a2"
    assert record["pdx_artifact_engine"]["release_commit"] == (
        "eba0d21ba665720a88546132f4779b4da6eb3beb"
    )
    assert record["pdx_adapter_media"]["version"] == "0.2.0a2"

    files = {
        **record["prodocux"]["files"],
        **record["pdx_artifact_engine"]["files"],
        **record["pdx_adapter_media"]["files"],
    }
    assert len(files) == 6
    assert all(len(digest) == 64 for digest in files.values())


def test_release_record_is_byte_identical_with_sibling_when_present() -> None:
    sibling = SIBLING / "compatibility" / RELEASE_RECORD.name
    if sibling.exists():
        assert RELEASE_RECORD.read_bytes() == sibling.read_bytes()
