from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "compatibility" / "pdx_prodocux_compatibility_v1.json"
SCHEMAS = (
    ROOT
    / "packages"
    / "pdx_artifact_core"
    / "src"
    / "pdx_artifact_core"
    / "schemas"
)
FROZEN_MANIFEST_SHA256 = (
    "0b860fc0a5693a96083de1560ff030398e762c9f0c9dc4c0975eceb1d6ca1303"
)


def test_compatibility_v1_manifest_is_byte_frozen() -> None:
    assert hashlib.sha256(MANIFEST.read_bytes()).hexdigest() == FROZEN_MANIFEST_SHA256


def test_compatibility_manifest_matches_pdx_core_release_surface() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "pdx_prodocux_compatibility_v1"
    assert manifest["status"] == "release_candidate"

    surface = manifest["pdx_artifact_core"]
    assert surface["distribution"] == "pdx-artifact-core"
    assert surface["version"] == "0.2.0a2"

    actual = {
        name: hashlib.sha256((SCHEMAS / name).read_bytes()).hexdigest()
        for name in surface["schemas"]
    }
    assert surface["schemas"] == actual
