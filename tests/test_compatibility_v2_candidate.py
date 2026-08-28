from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pdx_artifact_core
import pdx_artifact_engine
import tomllib

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "compatibility" / "pdx_prodocux_compatibility_v2.json"
SCHEMAS = (
    ROOT
    / "packages"
    / "pdx_artifact_core"
    / "src"
    / "pdx_artifact_core"
    / "schemas"
)
RELEASE_CANDIDATE_MANIFEST_SHA256 = (
    "c301aba7442b150b8186ce3b7cd8da99e9470ad0592c13f7f2818d38fd5f378e"
)
FROZEN_V1_MANIFEST_SHA256 = (
    "0b860fc0a5693a96083de1560ff030398e762c9f0c9dc4c0975eceb1d6ca1303"
)


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_compatibility_v2_candidate_bytes_are_reviewed() -> None:
    assert (
        hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
        == RELEASE_CANDIDATE_MANIFEST_SHA256
    )


def test_compatibility_v2_candidate_matches_pdx_core_surface() -> None:
    manifest = _manifest()
    assert manifest["schema_version"] == "pdx_prodocux_compatibility_v2"
    assert manifest["status"] == "release_candidate"
    assert manifest["compatibility_base"] == {
        "manifest": "pdx_prodocux_compatibility_v1.json",
        "sha256": FROZEN_V1_MANIFEST_SHA256,
    }

    surface = manifest["pdx_artifact_core"]
    assert surface["distribution"] == "pdx-artifact-engine"
    assert surface["component"] == "pdx-artifact-core"
    assert surface["version"] == "0.3.0a1"

    actual_schemas = {
        name: hashlib.sha256((SCHEMAS / name).read_bytes()).hexdigest()
        for name in surface["schemas"]
    }
    assert surface["schemas"] == actual_schemas

    missing_exports = [
        name for name in surface["additive_exports"] if not hasattr(pdx_artifact_core, name)
    ]
    assert missing_exports == []


def test_compatibility_v2_release_candidate_remains_unpublished() -> None:
    manifest = _manifest()
    assert manifest["status"] == "release_candidate"
    assert "No public pin exists" in manifest["integration"]["publication_gate"]


def test_release_candidate_versions_are_coherent() -> None:
    engine_metadata = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    core_metadata = tomllib.loads(
        (ROOT / "packages" / "pdx_artifact_core" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    frozen_surface_version = _manifest()["pdx_artifact_core"]["version"]
    package_versions = {
        engine_metadata["project"]["version"],
        core_metadata["project"]["version"],
        pdx_artifact_engine.__version__,
        pdx_artifact_core.__version__,
    }
    assert frozen_surface_version == "0.3.0a1"
    assert package_versions == {"0.3.0a3"}
