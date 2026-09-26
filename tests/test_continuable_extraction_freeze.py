from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "docs/continuable-extraction/contract-freeze.v1.json"


def _sha(path: Path) -> str:
    # Git stores these public contracts with LF line endings, while a Windows
    # checkout may materialize CRLF. Hash canonical UTF-8/LF text so the
    # freeze assertion is stable across supported CI and developer hosts.
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_continuable_extraction_freeze_matches_public_bytes() -> None:
    manifest = json.loads(FREEZE.read_text(encoding="utf-8"))
    assert manifest["status"] == "frozen"
    assert manifest["candidate_version"] == "0.3.0a11"
    assert manifest["publication_authorized"] is False
    schema_root = ROOT / "packages/pdx_artifact_core/src/pdx_artifact_core/schemas"
    for name, digest in manifest["schemas"].items():
        assert _sha(schema_root / name) == digest
    paths = {
        "pdx_artifact_core/continuable_extraction.py": ROOT / "packages/pdx_artifact_core/src/pdx_artifact_core/continuable_extraction.py",
        "pdx_artifact_engine/continuable_extraction/service.py": ROOT / "runtime/pdx_artifact_engine/continuable_extraction/service.py",
    }
    for name, digest in manifest["semantic_validators"].items():
        assert _sha(paths[name]) == digest
    adapter_root = ROOT / "adapters/prodocux/pdx_adapter_prodocux"
    for name in ("http_client.py", "verified_projection.py"):
        assert _sha(adapter_root / name) == manifest["adapter"][name]
    for name, digest in manifest["evidence"].items():
        assert _sha(FREEZE.parent / name) == digest
    for name, digest in manifest["legacy_compatibility"].items():
        assert _sha(ROOT / "compatibility" / name) == digest


def test_bilateral_freeze_records_parser_and_terminal_matrix() -> None:
    manifest = json.loads(FREEZE.read_text(encoding="utf-8"))
    assert set(manifest["adapter"]["formats"]) == {
        "pdf", "csv", "xlsx", "pptx", "image"
    }
    evidence = json.loads(
        (FREEZE.parent / "evidence-v1.json").read_text(encoding="utf-8")
    )
    assert evidence["terminal_reason_omissions"]["SOURCE_TOO_LARGE"] == "source_too_large"
