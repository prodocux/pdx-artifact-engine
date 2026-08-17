from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pdx_artifact_core import __version__


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


def test_compatibility_manifest_matches_pdx_core_release_surface() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "pdx_prodocux_compatibility_v1"
    assert manifest["status"] == "release_candidate"

    surface = manifest["pdx_artifact_core"]
    assert surface["distribution"] == "pdx-artifact-core"
    assert surface["version"] == __version__

    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in SCHEMAS.glob("*.json")
    }
    assert surface["schemas"] == actual
