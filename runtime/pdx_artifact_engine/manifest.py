from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    *,
    artifact_id: str,
    artifact_type: str,
    files: list[tuple[Path, str]],
    provenance: list[dict[str, Any]],
    verification: list[dict[str, str]],
    relative_to: Path | None = None,
) -> dict[str, Any]:
    manifest_files = []
    for path, role in files:
        display_path = path
        if relative_to is not None:
            try:
                display_path = path.relative_to(relative_to)
            except ValueError:
                pass
        entry = {"path": display_path.as_posix(), "role": role}
        if path.is_file():
            entry["sha256"] = sha256_file(path)
        manifest_files.append(entry)
    return {
        "schema_version": "pdx_artifact_manifest_v0",
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "files": manifest_files,
        "provenance": provenance,
        "verification": verification,
    }


def write_manifest(manifest: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
